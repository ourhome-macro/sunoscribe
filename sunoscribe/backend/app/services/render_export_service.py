from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.artifact import Artifact
from app.models.enums import ArtifactStatus, ArtifactStorageBackend, ArtifactType
from app.models.score import Score
from app.models.score_revision import ScoreRevision
from app.modules.pitch import MidiExporter
from app.services.workspace import ProjectWorkspace
from app.utils.errors import ValidationAppError

_DIVISIONS = 480
_PITCH_PATTERN = re.compile(r"^([A-Ga-g])([#b]?)(-?\d+)$")
_MAJOR_FIFTHS = {
    "C": 0,
    "G": 1,
    "D": 2,
    "A": 3,
    "E": 4,
    "B": 5,
    "F#": 6,
    "C#": 7,
    "F": -1,
    "Bb": -2,
    "Eb": -3,
    "Ab": -4,
    "Db": -5,
    "Gb": -6,
    "Cb": -7,
}
_MINOR_FIFTHS = {
    "A": 0,
    "E": 1,
    "B": 2,
    "F#": 3,
    "C#": 4,
    "G#": 5,
    "D#": 6,
    "A#": 7,
    "D": -1,
    "G": -2,
    "C": -3,
    "F": -4,
    "Bb": -5,
    "Eb": -6,
    "Ab": -7,
}


class RenderExportService:
    """Generate revision-scoped artifacts from a selected ScoreRevision."""

    def ensure_core_exports(
        self,
        db: Session,
        *,
        score: Score,
        revision: ScoreRevision,
        task_id: str | None = None,
    ) -> dict[str, Artifact]:
        artifacts = {
            ArtifactType.MIDI.value: self.generate_export_artifact(
                db,
                score=score,
                revision=revision,
                export_format=ArtifactType.MIDI.value,
                task_id=task_id,
            ),
            ArtifactType.MUSICXML.value: self.generate_export_artifact(
                db,
                score=score,
                revision=revision,
                export_format=ArtifactType.MUSICXML.value,
                task_id=task_id,
            ),
            ArtifactType.SCORE_VIEW.value: self.generate_export_artifact(
                db,
                score=score,
                revision=revision,
                export_format=ArtifactType.SCORE_VIEW.value,
                task_id=task_id,
            ),
        }
        return artifacts

    def generate_export_artifact(
        self,
        db: Session,
        *,
        score: Score,
        revision: ScoreRevision,
        export_format: str,
        task_id: str | None = None,
    ) -> Artifact:
        format_key = str(export_format).strip().lower()
        artifact_type, filename, mime_type, payload = self._build_export_payload(revision=revision, format_key=format_key)

        workspace = ProjectWorkspace(project_id=str(score.project_id))
        workspace.ensure_structure()
        export_dir = workspace.revision_exports_dir(str(revision.id))
        export_dir.mkdir(parents=True, exist_ok=True)
        target_path = export_dir / filename
        target_path.write_bytes(payload)

        checksum = hashlib.sha256(payload).hexdigest()
        artifact = self._get_existing_artifact(db, revision_id=str(revision.id), artifact_type=artifact_type)
        if artifact is None:
            artifact = Artifact(
                project_id=score.project_id,
                score_id=score.id,
                score_revision_id=revision.id,
                task_id=_optional_uuid(task_id),
                artifact_type=artifact_type,
            )

        artifact.task_id = _optional_uuid(task_id)
        artifact.status = ArtifactStatus.AVAILABLE.value
        artifact.storage_backend = ArtifactStorageBackend.WORKSPACE.value
        artifact.storage_path = str(target_path)
        artifact.filename = filename
        artifact.mime_type = mime_type
        artifact.file_size_bytes = len(payload)
        artifact.checksum = checksum
        artifact.error_message = None
        artifact.artifact_metadata = {
            "export_format": format_key,
            "revision_number": int(revision.revision_number),
            "revision_type": str(revision.revision_type),
        }
        db.add(artifact)
        return artifact

    def load_export_bytes(
        self,
        db: Session,
        *,
        score: Score,
        revision: ScoreRevision,
        export_format: str,
    ) -> tuple[bytes, str, str]:
        format_key = str(export_format).strip().lower()
        artifact_type = self._export_format_to_artifact_type(format_key)
        if artifact_type == ArtifactType.PDF.value:
            payload = build_summary_pdf(revision=revision)
            return payload, "application/pdf", f"score_{revision.id}.pdf"

        artifact = self._get_existing_artifact(db, revision_id=str(revision.id), artifact_type=artifact_type)
        if artifact is None or not artifact.storage_path:
            artifact = self.generate_export_artifact(
                db,
                score=score,
                revision=revision,
                export_format=format_key,
            )

        if not artifact.storage_path:
            raise ValidationAppError(f"missing storage path for {artifact.artifact_type} artifact")

        target_path = Path(artifact.storage_path)
        if not target_path.exists() or not target_path.is_file():
            artifact = self.generate_export_artifact(
                db,
                score=score,
                revision=revision,
                export_format=format_key,
            )
            target_path = Path(str(artifact.storage_path or ""))

        if not target_path.exists() or not target_path.is_file():
            raise ValidationAppError(f"revision export artifact is missing on disk: {artifact_type}")

        return target_path.read_bytes(), str(artifact.mime_type), str(artifact.filename)

    def _build_export_payload(self, *, revision: ScoreRevision, format_key: str) -> tuple[str, str, str, bytes]:
        score_data = _revision_score_data_for_export(revision)
        if format_key == ArtifactType.MIDI.value:
            payload = build_midi_bytes_from_score_data(score_data)
            if payload is None:
                raise ValidationAppError("selected score revision cannot be exported as MIDI")
            return ArtifactType.MIDI.value, "score.mid", "audio/midi", payload

        if format_key == ArtifactType.MUSICXML.value:
            payload = build_musicxml_bytes_from_score_data(score_data)
            if payload is None:
                raise ValidationAppError("selected score revision cannot be exported as MusicXML")
            return ArtifactType.MUSICXML.value, "score.musicxml", "application/vnd.recordare.musicxml+xml", payload

        if format_key == ArtifactType.SCORE_VIEW.value:
            payload = json.dumps(score_data, ensure_ascii=False, indent=2).encode("utf-8")
            return ArtifactType.SCORE_VIEW.value, "score_view.json", "application/json", payload

        if format_key == ArtifactType.PDF.value:
            payload = build_summary_pdf(revision=revision)
            return ArtifactType.PDF.value, "score.pdf", "application/pdf", payload

        raise ValidationAppError("only midi/musicxml/pdf/view exports are supported")

    def _get_existing_artifact(self, db: Session, *, revision_id: str, artifact_type: str) -> Artifact | None:
        revision_uuid = _optional_uuid(revision_id)
        stmt = (
            select(Artifact)
            .where(
                Artifact.score_revision_id == revision_uuid,
                Artifact.artifact_type == artifact_type,
            )
            .order_by(Artifact.created_at.desc())
        )
        return db.execute(stmt).scalar_one_or_none()

    def _export_format_to_artifact_type(self, format_key: str) -> str:
        normalized = str(format_key).strip().lower()
        mapping = {
            "midi": ArtifactType.MIDI.value,
            "musicxml": ArtifactType.MUSICXML.value,
            "pdf": ArtifactType.PDF.value,
            "view": ArtifactType.SCORE_VIEW.value,
            "score_view": ArtifactType.SCORE_VIEW.value,
        }
        artifact_type = mapping.get(normalized)
        if artifact_type is None:
            raise ValidationAppError("only midi/pdf/musicxml/view export formats are supported")
        return artifact_type


def build_midi_bytes_from_score_data(score_data: dict[str, Any] | None) -> bytes | None:
    if not isinstance(score_data, dict):
        return None

    measures = score_data.get("measures")
    if not isinstance(measures, list) or not measures:
        return None

    bpm_raw = score_data.get("bpm")
    if bpm_raw is None and isinstance(score_data.get("meta"), dict):
        bpm_raw = score_data["meta"].get("bpm")

    try:
        bpm = float(bpm_raw)
    except (TypeError, ValueError):
        return None

    if bpm <= 0:
        return None

    try:
        exporter = MidiExporter()
        return exporter.export_from_score_data(score_data=score_data, bpm=bpm)
    except Exception as exc:
        raise ValidationAppError("failed to export MIDI from score revision") from exc


def _revision_score_data_for_export(revision: ScoreRevision) -> dict[str, Any]:
    score_data = revision.score_data if isinstance(revision.score_data, dict) else {}
    score_ir = revision.score_ir if isinstance(revision.score_ir, dict) else {}
    embedded_score_ir = score_data.get("score_ir") if isinstance(score_data.get("score_ir"), dict) else None
    if not score_ir:
        raise ValidationAppError("selected score revision is missing score_ir")
    if embedded_score_ir != score_ir or score_data.get("source_of_truth") != "score_ir":
        raise ValidationAppError("selected score revision export data is not derived from score_ir")
    return score_data


def build_musicxml_bytes_from_score_data(score_data: dict[str, Any] | None) -> bytes | None:
    if not isinstance(score_data, dict):
        return None

    measures = score_data.get("measures")
    if not isinstance(measures, list) or not measures:
        return None

    bpm = _extract_bpm(score_data)
    time_signature = _extract_time_signature(score_data)
    fifths = _extract_key_fifths(score_data)

    root = ET.Element("score-partwise", version="3.1")
    part_list = ET.SubElement(root, "part-list")
    score_part = ET.SubElement(part_list, "score-part", id="P1")
    ET.SubElement(score_part, "part-name").text = "Voice"
    part = ET.SubElement(root, "part", id="P1")
    chords_by_measure = _group_items_by_measure(score_data.get("chord_timeline"))
    sections_by_measure = _group_sections_by_measure(score_data.get("form_sections"))

    has_any_note = False
    for idx, measure in enumerate(measures, start=1):
        if not isinstance(measure, dict):
            continue
        measure_num = str(measure.get("measure_num") or idx)
        measure_num_int = _safe_int(measure.get("measure_num"), fallback=idx)
        m = ET.SubElement(part, "measure", number=measure_num)

        if idx == 1:
            attrs = ET.SubElement(m, "attributes")
            ET.SubElement(attrs, "divisions").text = str(_DIVISIONS)
            key = ET.SubElement(attrs, "key")
            ET.SubElement(key, "fifths").text = str(fifths)
            time = ET.SubElement(attrs, "time")
            ET.SubElement(time, "beats").text = str(time_signature[0])
            ET.SubElement(time, "beat-type").text = str(time_signature[1])
            clef = ET.SubElement(attrs, "clef")
            ET.SubElement(clef, "sign").text = "G"
            ET.SubElement(clef, "line").text = "2"
            if bpm and bpm > 0:
                ET.SubElement(m, "sound", tempo=str(round(float(bpm), 3)))

        for section in sections_by_measure.get(measure_num_int, []):
            _append_musicxml_section_direction(m, section)

        for chord in chords_by_measure.get(measure_num_int, []):
            _append_musicxml_harmony(m, chord)

        note_list = measure.get("notes")
        if not isinstance(note_list, list):
            continue

        for note in note_list:
            if not isinstance(note, dict):
                continue

            pitch_info = _parse_pitch(note.get("pitch"))
            duration_beats = _safe_float(note.get("duration_beats"), fallback=1.0)
            duration_value = max(1, int(round(duration_beats * _DIVISIONS)))

            n = ET.SubElement(m, "note")
            if pitch_info is None:
                ET.SubElement(n, "rest")
            else:
                step, alter, octave = pitch_info
                pitch = ET.SubElement(n, "pitch")
                ET.SubElement(pitch, "step").text = step
                if alter != 0:
                    ET.SubElement(pitch, "alter").text = str(alter)
                ET.SubElement(pitch, "octave").text = str(octave)
                has_any_note = True

            ET.SubElement(n, "duration").text = str(duration_value)
            ET.SubElement(n, "voice").text = "1"
            note_type = note.get("note_type")
            ET.SubElement(n, "type").text = _map_note_type(note_type, duration_beats)
            if _is_dotted_note(note_type):
                ET.SubElement(n, "dot")
            if _is_triplet_note(note_type):
                time_modification = ET.SubElement(n, "time-modification")
                ET.SubElement(time_modification, "actual-notes").text = "3"
                ET.SubElement(time_modification, "normal-notes").text = "2"

            lyric = note.get("lyric")
            if isinstance(lyric, str) and lyric.strip():
                lyric_tag = ET.SubElement(n, "lyric")
                ET.SubElement(lyric_tag, "text").text = lyric.strip()

    if not has_any_note:
        return None

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def build_summary_pdf(*, revision: ScoreRevision) -> bytes:
    score_data = revision.score_data if isinstance(revision.score_data, dict) else {}
    meta = score_data.get("meta") if isinstance(score_data.get("meta"), dict) else {}
    measures = score_data.get("measures") if isinstance(score_data.get("measures"), list) else []
    notes_count = 0
    for measure in measures:
        if isinstance(measure, dict) and isinstance(measure.get("notes"), list):
            notes_count += len(measure["notes"])

    lines = [
        "SunoScribe Score Export",
        f"Revision ID: {revision.id}",
        f"Score ID: {revision.score_id}",
        f"Key: {meta.get('key', revision.key)}",
        f"BPM: {meta.get('bpm', score_data.get('bpm', 'N/A'))}",
        f"Measures: {len(measures)}",
        f"Notes: {notes_count}",
    ]
    return _build_text_pdf(lines)


def _extract_bpm(score_data: dict[str, Any]) -> float | None:
    bpm_raw = score_data.get("bpm")
    if bpm_raw is None and isinstance(score_data.get("meta"), dict):
        bpm_raw = score_data["meta"].get("bpm")
    try:
        bpm = float(bpm_raw)
    except (TypeError, ValueError):
        return None
    return bpm if bpm > 0 else None


def _extract_time_signature(score_data: dict[str, Any]) -> tuple[int, int]:
    raw = score_data.get("time_signature")
    if raw is None and isinstance(score_data.get("meta"), dict):
        raw = score_data["meta"].get("time_signature")
    text = str(raw or "4/4")
    if "/" in text:
        left, right = text.split("/", 1)
        try:
            beats = max(1, int(left))
            beat_type = max(1, int(right))
            return beats, beat_type
        except ValueError:
            return 4, 4
    return 4, 4


def _extract_key_fifths(score_data: dict[str, Any]) -> int:
    raw = score_data.get("key")
    if raw is None and isinstance(score_data.get("meta"), dict):
        raw = score_data["meta"].get("key")
    text = str(raw or "C Major").strip()
    if " " in text:
        tonic, mode = text.split(" ", 1)
    else:
        tonic, mode = text, "Major"
    tonic = tonic.replace("鈾?", "#").replace("鈾?", "b")
    mode_norm = mode.strip().lower()
    if mode_norm.startswith("min"):
        return _MINOR_FIFTHS.get(tonic, 0)
    return _MAJOR_FIFTHS.get(tonic, 0)


def _parse_pitch(raw_pitch: Any) -> tuple[str, int, int] | None:
    if not isinstance(raw_pitch, str):
        return None
    match = _PITCH_PATTERN.match(raw_pitch.strip())
    if not match:
        return None
    step = match.group(1).upper()
    accidental = match.group(2)
    octave = int(match.group(3))
    alter = 1 if accidental == "#" else (-1 if accidental == "b" else 0)
    return step, alter, octave


def _map_note_type(note_type_raw: Any, duration_beats: float) -> str:
    if isinstance(note_type_raw, str):
        normalized = note_type_raw.strip().lower()
        mapping = {
            "whole": "whole",
            "half": "half",
            "quarter": "quarter",
            "eighth": "eighth",
            "sixteenth": "16th",
            "thirty_second": "32nd",
            "dotted_quarter": "quarter",
            "dotted_eighth": "eighth",
            "triplet": "eighth",
        }
        if normalized in mapping:
            return mapping[normalized]

    if duration_beats >= 3.5:
        return "whole"
    if duration_beats >= 1.75:
        return "half"
    if duration_beats >= 0.75:
        return "quarter"
    if duration_beats >= 0.375:
        return "eighth"
    if duration_beats >= 0.1875:
        return "16th"
    return "32nd"


def _is_dotted_note(note_type_raw: Any) -> bool:
    return isinstance(note_type_raw, str) and note_type_raw.strip().lower().startswith("dotted_")


def _is_triplet_note(note_type_raw: Any) -> bool:
    return isinstance(note_type_raw, str) and note_type_raw.strip().lower() == "triplet"


def _safe_float(value: Any, *, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _safe_int(value: Any, *, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _group_items_by_measure(items: Any) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    if not isinstance(items, list):
        return grouped
    for item in items:
        if not isinstance(item, dict):
            continue
        measure_num = _safe_int(item.get("measure_num"), fallback=0)
        if measure_num <= 0:
            continue
        grouped.setdefault(measure_num, []).append(item)
    return grouped


def _group_sections_by_measure(items: Any) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    if not isinstance(items, list):
        return grouped
    for item in items:
        if not isinstance(item, dict):
            continue
        measure_start = _safe_int(item.get("measure_start"), fallback=0)
        if measure_start <= 0:
            continue
        grouped.setdefault(measure_start, []).append(item)
    return grouped


def _append_musicxml_section_direction(measure_el: ET.Element, section: dict[str, Any]) -> None:
    label = str(section.get("label") or section.get("id") or "").strip()
    if not label:
        return
    direction = ET.SubElement(measure_el, "direction", placement="above")
    direction_type = ET.SubElement(direction, "direction-type")
    ET.SubElement(direction_type, "rehearsal").text = label


def _append_musicxml_harmony(measure_el: ET.Element, chord: dict[str, Any]) -> None:
    root_name = str(chord.get("root") or "").strip()
    if not root_name:
        symbol = str(chord.get("symbol") or "").strip()
        if not symbol:
            return
        root_name = symbol.split("/", 1)[0].strip()
    parsed_root = _parse_chord_root(root_name)
    if parsed_root is None:
        return

    harmony = ET.SubElement(measure_el, "harmony")
    root = ET.SubElement(harmony, "root")
    ET.SubElement(root, "root-step").text = parsed_root[0]
    if parsed_root[1] != 0:
        ET.SubElement(root, "root-alter").text = str(parsed_root[1])

    ET.SubElement(harmony, "kind").text = _map_chord_kind(chord.get("quality"))

    bass_name = chord.get("bass")
    if isinstance(bass_name, str) and bass_name.strip():
        parsed_bass = _parse_chord_root(bass_name)
        if parsed_bass is not None:
            bass = ET.SubElement(harmony, "bass")
            ET.SubElement(bass, "bass-step").text = parsed_bass[0]
            if parsed_bass[1] != 0:
                ET.SubElement(bass, "bass-alter").text = str(parsed_bass[1])


def _parse_chord_root(value: str) -> tuple[str, int] | None:
    text = str(value or "").strip().replace("鈾?", "#").replace("鈾?", "b")
    if not text:
        return None
    match = re.match(r"^([A-Ga-g])([#b]?)(?:.*)$", text)
    if not match:
        return None
    step = match.group(1).upper()
    accidental = match.group(2)
    alter = 1 if accidental == "#" else (-1 if accidental == "b" else 0)
    return step, alter


def _map_chord_kind(raw_quality: Any) -> str:
    quality = str(raw_quality or "").strip().lower()
    if quality in {"m", "min", "minor"}:
        return "minor"
    if quality in {"dim", "diminished"}:
        return "diminished"
    if quality in {"aug", "augmented"}:
        return "augmented"
    if quality in {"5", "power"}:
        return "power"
    return "major"


def _build_text_pdf(lines: list[str]) -> bytes:
    def esc(text: str) -> str:
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    y = 800
    parts = ["BT", "/F1 12 Tf"]
    for idx, line in enumerate(lines):
        if idx == 0:
            parts.append(f"50 {y} Td")
        else:
            parts.append("0 -18 Td")
        parts.append(f"({esc(str(line))}) Tj")
    parts.append("ET")
    content = "\n".join(parts).encode("latin-1", errors="replace")

    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Count 1 /Kids [3 0 R] >>")
    objects.append(
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
    )
    objects.append(b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n" + content + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for idx, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{idx} 0 obj\n".encode("ascii"))
        output.extend(obj)
        output.extend(b"\nendobj\n")

    xref_start = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        output.extend(f"{off:010d} 00000 n \n".encode("ascii"))

    output.extend(
        (
            "trailer\n"
            f"<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            "startxref\n"
            f"{xref_start}\n"
            "%%EOF\n"
        ).encode("ascii")
    )
    return bytes(output)


def _optional_uuid(raw: str | uuid.UUID | None) -> uuid.UUID | None:
    if raw is None or isinstance(raw, uuid.UUID):
        return raw
    text = str(raw).strip()
    if not text:
        return None
    return uuid.UUID(text)
