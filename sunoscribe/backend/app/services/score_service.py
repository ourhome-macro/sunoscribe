import asyncio
import json
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse
from typing import Any
from xml.etree import ElementTree as ET

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import ProjectStatus, ScoreType
from app.models.lyrics import Lyrics
from app.models.project import Project
from app.models.score import Score
from app.models.user import User
from app.config import settings
from app.modules.pitch import MidiExporter
from app.services.audio_analysis_service import AudioAnalysisOptions, AudioAnalysisResult, AudioAnalysisService
from app.services.workspace import ProjectWorkspace
from app.utils.errors import NotFoundError, ValidationAppError


ALLOWED_EXPORT_FORMATS = {"midi", "pdf", "musicxml"}
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


def get_score_by_project_id(db: Session, *, user: User, project_id: str) -> Score:
    project_uuid = _parse_uuid(project_id, "project_id")
    stmt = (
        select(Score)
        .join(Project, Score.project_id == Project.id)
        .where(Project.id == project_uuid, Project.user_id == user.id)
    )
    score = db.execute(stmt).scalar_one_or_none()
    if score is None:
        raise NotFoundError("项目谱子不存在")
    return score


def generate_or_regenerate_score(
    db: Session,
    *,
    user: User,
    project_id: str,
    score_type: ScoreType,
    key: str,
) -> Score:
    project_uuid = _parse_uuid(project_id, "project_id")
    project_stmt = select(Project).where(Project.id == project_uuid, Project.user_id == user.id)
    project = db.execute(project_stmt).scalar_one_or_none()
    if project is None:
        raise NotFoundError("项目不存在")

    audio_path = str(project.audio_path or "").strip()
    if not audio_path:
        raise ValidationAppError("项目缺少可分析的音视频文件")

    score_stmt = select(Score).where(Score.project_id == project.id)
    score = db.execute(score_stmt).scalar_one_or_none()
    if score is None:
        score = Score(project_id=project.id)
        db.add(score)

    now = datetime.now(timezone.utc).isoformat()
    score.score_type = score_type.value
    score.key = key
    analysis_result = _run_audio_analysis(project)
    score.score_data = _build_score_data_from_analysis(
        analysis_result,
        project=project,
        score_type=score_type,
        key=key,
        generated_at=now,
    )

    # The task worker marks failure paths; reaching this point means analysis produced a usable score.
    project.status = ProjectStatus.COMPLETED.value
    project.progress = 100
    db.add(project)
    db.add(score)

    lyrics_stmt = select(Lyrics).where(Lyrics.project_id == project.id)
    lyrics = db.execute(lyrics_stmt).scalar_one_or_none()
    if lyrics is None:
        lyrics = Lyrics(project_id=project.id, text="", timeline=[])

    lyrics.text = _build_lyrics_text(analysis_result.lyrics_segments)
    lyrics.timeline = list(analysis_result.lyrics_segments)
    db.add(lyrics)

    db.commit()
    db.refresh(score)
    return score


def _build_score_data_from_analysis(
    analysis_result: AudioAnalysisResult,
    *,
    project: Project,
    score_type: ScoreType,
    key: str,
    generated_at: str,
) -> dict[str, Any]:
    source_score_data = analysis_result.score_data
    if not isinstance(source_score_data, dict):
        source_score_data = analysis_result.score_ir if isinstance(analysis_result.score_ir, dict) else {}

    score_data = dict(source_score_data)
    meta = score_data.get("meta") if isinstance(score_data.get("meta"), dict) else {}
    score_data["meta"] = {
        **meta,
        "project_id": str(project.id),
        "score_type": score_type.value,
        "requested_key": key,
        "generated_by": "audio_analysis_service",
        "generated_at": generated_at,
        "uploaded_audio_path": project.audio_path,
        "source_audio_path": analysis_result.source_audio_path,
    }
    score_data["generated_by"] = "audio_analysis_service"
    score_data["generated_at"] = generated_at
    score_data["audio_path"] = project.audio_path
    score_data["source_audio_path"] = analysis_result.source_audio_path
    score_data["normalized_audio_path"] = analysis_result.normalized_audio_path
    score_data["vocals_path"] = analysis_result.vocals_path
    score_data["accompaniment_path"] = analysis_result.accompaniment_path
    score_data["stem_paths"] = dict(analysis_result.stem_paths or {})
    if analysis_result.midi_path:
        score_data["midi_path"] = analysis_result.midi_path
        score_data["final_midi_path"] = analysis_result.midi_path
    score_data["pitch_result"] = analysis_result.pitch_result
    score_data["analysis_ir"] = analysis_result.analysis_ir
    score_data["semantic_audio"] = analysis_result.semantic_audio
    score_data["score_ir"] = analysis_result.score_ir
    score_data["alignment"] = {
        "source": analysis_result.alignment_source,
        "accepted": analysis_result.alignment_accepted,
        "baseline": analysis_result.baseline_alignment,
        "refined": analysis_result.refined_alignment,
        "final": analysis_result.final_alignment,
        "warnings_before": list(analysis_result.validator_warnings_before or []),
        "warnings_after": list(analysis_result.validator_warnings_after or []),
        "refine_warnings": list(analysis_result.refine_warnings or []),
    }
    score_data["warnings"] = _merge_unique_strings(score_data.get("warnings"), analysis_result.warnings)
    return score_data


def _merge_unique_strings(*chunks: Any) -> list[str]:
    merged: list[str] = []
    for chunk in chunks:
        if isinstance(chunk, str):
            values = [chunk]
        elif isinstance(chunk, list):
            values = chunk
        else:
            values = []
        for item in values:
            text = str(item).strip()
            if text and text not in merged:
                merged.append(text)
    return merged


def update_score(
    db: Session,
    *,
    user: User,
    score_id: str,
    score_type: ScoreType | None,
    key: str | None,
    vocal_range: str | None,
    recommended_voice: str | None,
    emotion: str | None,
    score_data: dict[str, Any] | None,
) -> Score:
    score_uuid = _parse_uuid(score_id, "score_id")
    stmt = (
        select(Score)
        .join(Project, Score.project_id == Project.id)
        .where(Score.id == score_uuid, Project.user_id == user.id)
    )
    score = db.execute(stmt).scalar_one_or_none()
    if score is None:
        raise NotFoundError("谱子不存在")

    if score_type is not None:
        score.score_type = score_type.value
    if key is not None:
        score.key = key
    if vocal_range is not None:
        score.vocal_range = vocal_range
    if recommended_voice is not None:
        score.recommended_voice = recommended_voice
    if emotion is not None:
        score.emotion = emotion
    if score_data is not None:
        score.score_data = score_data

    db.add(score)
    db.commit()
    db.refresh(score)
    return score


def export_score(
    db: Session,
    *,
    user: User,
    score_id: str,
    export_format: str,
) -> tuple[bytes, str, str]:
    fmt = str(export_format).strip().lower()
    if fmt not in ALLOWED_EXPORT_FORMATS:
        raise ValidationAppError("仅支持导出格式: midi/pdf/musicxml")

    score = get_score_by_id(db, user=user, score_id=score_id)

    if fmt == "midi":
        content = _export_midi_bytes(score)
        return content, "audio/midi", f"score_{score.id}.mid"

    if fmt == "pdf":
        content = _export_pdf_bytes(score)
        return content, "application/pdf", f"score_{score.id}.pdf"

    content = _export_musicxml_bytes(score)
    return content, "application/vnd.recordare.musicxml+xml", f"score_{score.id}.musicxml"


def get_score_by_id(db: Session, *, user: User, score_id: str) -> Score:
    score_uuid = _parse_uuid(score_id, "score_id")
    stmt = (
        select(Score)
        .join(Project, Score.project_id == Project.id)
        .where(Score.id == score_uuid, Project.user_id == user.id)
    )
    score = db.execute(stmt).scalar_one_or_none()
    if score is None:
        raise NotFoundError("谱子不存在")
    return score


def _parse_uuid(raw: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(raw))
    except (TypeError, ValueError) as exc:
        raise ValidationAppError(f"{field_name} 不是合法 UUID") from exc


def _export_midi_bytes(score: Score) -> bytes:
    existing_path = _find_existing_midi_path(score)
    if existing_path is not None:
        return existing_path.read_bytes()

    generated = _build_midi_from_score_data(score.score_data)
    if generated is not None:
        return generated

    raise ValidationAppError("当前谱子没有可导出的 MIDI 产物")


def _find_existing_midi_path(score: Score) -> Path | None:
    return _find_existing_export_path(
        score,
        score_data_keys=("midi_path", "final_midi_path", "raw_pitch_midi_path", "export_midi_path"),
        default_workspace_files=("final_score.mid", "raw_pitch.mid"),
    )


def _export_musicxml_bytes(score: Score) -> bytes:
    existing_path = _find_existing_export_path(
        score,
        score_data_keys=("musicxml_path", "export_musicxml_path", "xml_path"),
        default_workspace_files=("final_score.musicxml", "final_score.xml"),
    )
    if existing_path is not None:
        return existing_path.read_bytes()

    generated = _build_musicxml_from_score_data(score.score_data)
    if generated is not None:
        return generated

    raise ValidationAppError("当前谱子没有可导出的 MusicXML 产物")


def _export_pdf_bytes(score: Score) -> bytes:
    existing_path = _find_existing_export_path(
        score,
        score_data_keys=("pdf_path", "export_pdf_path"),
        default_workspace_files=("final_score.pdf",),
    )
    if existing_path is not None:
        return existing_path.read_bytes()

    return _build_summary_pdf(score)


def _build_midi_from_score_data(score_data: dict[str, Any] | None) -> bytes | None:
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
        return exporter.export_from_measures(measures=measures, bpm=bpm)
    except Exception:
        return None


def _find_existing_export_path(
    score: Score,
    *,
    score_data_keys: tuple[str, ...],
    default_workspace_files: tuple[str, ...],
) -> Path | None:
    candidates: list[Path] = []
    score_data = score.score_data if isinstance(score.score_data, dict) else {}
    workspace: ProjectWorkspace | None = None
    workspace_root: Path | None = None

    try:
        workspace = ProjectWorkspace(project_id=str(score.project_id))
        workspace_root = workspace.project_dir.resolve(strict=False)
    except Exception:
        workspace = None
        workspace_root = None

    for key in score_data_keys:
        raw = score_data.get(key)
        candidate = _resolve_workspace_scoped_path(raw, workspace_root=workspace_root)
        if candidate is not None:
            candidates.append(candidate)

    if workspace is not None:
        for filename in default_workspace_files:
            candidates.append(workspace.exports_dir / filename)
        # Keep backward compatibility for historical pitch output.
        candidates.extend([workspace.final_midi_path, workspace.raw_pitch_midi_path])

    for path in candidates:
        if path.exists() and path.is_file():
            return path
    return None


def _run_audio_analysis(project: Project) -> AudioAnalysisResult:
    raw_audio_path = str(project.audio_path or "").strip()
    if not raw_audio_path:
        raise ValidationAppError("项目缺少可分析的音视频文件")

    with _materialize_analysis_input(raw_audio_path) as input_path:
        service = AudioAnalysisService()
        options = AudioAnalysisOptions(project_id=str(project.id))
        result = asyncio.run(service.process_audio(input_path, options))

    score_ir = result.score_ir if isinstance(result.score_ir, dict) else {}
    meta = score_ir.get("meta") if isinstance(score_ir.get("meta"), dict) else {}
    analysis_info = meta.get("analysis_info") if isinstance(meta.get("analysis_info"), dict) else {}
    if analysis_info.get("fallback"):
        raise ValidationAppError("音频分析失败，未生成有效谱面")

    notes = score_ir.get("notes")
    if not isinstance(notes, list) or not notes:
        raise ValidationAppError("音频分析未产出可用音符，无法生成谱子")

    return result


class _LocalAnalysisInput:
    def __init__(self, path: Path) -> None:
        self.path = path

    def __enter__(self) -> Path:
        if not self.path.exists() or not self.path.is_file():
            raise ValidationAppError("项目音视频文件不存在或不可访问")
        return self.path

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class _TemporaryAnalysisInput:
    def __init__(self, source_uri: str) -> None:
        self.source_uri = source_uri
        self._temp_dir: tempfile.TemporaryDirectory[str] | None = None

    def __enter__(self) -> Path:
        bucket, object_name = _parse_s3_uri(self.source_uri)
        self._temp_dir = tempfile.TemporaryDirectory(prefix="sunoscribe-analysis-")
        target = Path(self._temp_dir.name) / Path(object_name).name
        if not target.suffix:
            target = target.with_suffix(".bin")
        _download_minio_object(bucket=bucket, object_name=object_name, target_path=target)
        return target

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._temp_dir is not None:
            self._temp_dir.cleanup()


def _materialize_analysis_input(raw_audio_path: str) -> _LocalAnalysisInput | _TemporaryAnalysisInput:
    if raw_audio_path.lower().startswith("s3://"):
        return _TemporaryAnalysisInput(raw_audio_path)
    return _LocalAnalysisInput(Path(raw_audio_path))


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme.lower() != "s3" or not parsed.netloc or not parsed.path.strip("/"):
        raise ValidationAppError("项目音视频对象存储路径无效")
    return parsed.netloc, unquote(parsed.path.lstrip("/"))


def _download_minio_object(*, bucket: str, object_name: str, target_path: Path) -> None:
    if not settings.minio_endpoint or not settings.minio_access_key or not settings.minio_secret_key:
        raise ValidationAppError("对象存储配置不完整，无法读取项目音视频文件")

    try:
        from minio import Minio
    except Exception as exc:
        raise ValidationAppError("未安装 minio 依赖，请先安装 minio 包") from exc

    client_kwargs: dict[str, Any] = {
        "endpoint": settings.minio_endpoint,
        "access_key": settings.minio_access_key,
        "secret_key": settings.minio_secret_key,
        "secure": bool(settings.minio_secure),
    }
    if settings.minio_region:
        client_kwargs["region"] = settings.minio_region
    client = Minio(**client_kwargs)

    target_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        client.fget_object(bucket, object_name, str(target_path))
    except Exception as exc:
        raise ValidationAppError("项目音视频对象不存在或不可访问") from exc


def _build_score_payload(
    *,
    analysis_result: AudioAnalysisResult,
    generated_at: str,
    project_id: uuid.UUID,
    score_type: ScoreType,
    requested_key: str,
) -> dict[str, Any]:
    score_data = analysis_result.score_ir if isinstance(analysis_result.score_ir, dict) else {}
    payload = dict(score_data)
    meta = payload.get("meta")
    payload_meta = dict(meta) if isinstance(meta, dict) else {}
    payload_meta["project_id"] = str(project_id)
    payload_meta["score_type"] = score_type.value
    payload_meta["requested_key"] = requested_key
    payload_meta["generated_at"] = generated_at
    payload["meta"] = payload_meta
    payload["generated_by"] = "audio_analysis_service"
    if analysis_result.midi_path:
        payload["final_midi_path"] = analysis_result.midi_path
    if analysis_result.warnings:
        payload["warnings"] = list(analysis_result.warnings)
    return payload


def _build_lyrics_text(lyrics_segments: list[dict[str, Any]]) -> str:
    lines = [
        str(segment.get("text", "")).strip()
        for segment in lyrics_segments
        if isinstance(segment, dict) and str(segment.get("text", "")).strip()
    ]
    return "\n".join(lines)


def _resolve_workspace_scoped_path(raw: Any, *, workspace_root: Path | None) -> Path | None:
    if workspace_root is None or not isinstance(raw, str) or not raw.strip():
        return None

    raw_path = Path(raw.strip()).expanduser()
    candidate_paths = [raw_path.resolve(strict=False)]
    if not raw_path.is_absolute():
        candidate_paths.append((workspace_root / raw_path).resolve(strict=False))

    for candidate in candidate_paths:
        try:
            candidate.relative_to(workspace_root)
            return candidate
        except ValueError:
            continue

    return None


def _build_musicxml_from_score_data(score_data: dict[str, Any] | None) -> bytes | None:
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

    xml_body = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return xml_body


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
    tonic = tonic.replace("♯", "#").replace("♭", "b")
    mode_norm = mode.strip().lower()
    if mode_norm.startswith("min"):
        return _MINOR_FIFTHS.get(tonic, 0)
    return _MAJOR_FIFTHS.get(tonic, 0)


def _parse_pitch(raw_pitch: Any) -> tuple[str, int, int] | None:
    if not isinstance(raw_pitch, str):
        return None
    m = _PITCH_PATTERN.match(raw_pitch.strip())
    if not m:
        return None
    step = m.group(1).upper()
    accidental = m.group(2)
    octave = int(m.group(3))
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

    kind_text = _map_chord_kind(chord.get("quality"))
    ET.SubElement(harmony, "kind").text = kind_text

    bass_name = chord.get("bass")
    if isinstance(bass_name, str) and bass_name.strip():
        parsed_bass = _parse_chord_root(bass_name)
        if parsed_bass is not None:
            bass = ET.SubElement(harmony, "bass")
            ET.SubElement(bass, "bass-step").text = parsed_bass[0]
            if parsed_bass[1] != 0:
                ET.SubElement(bass, "bass-alter").text = str(parsed_bass[1])


def _parse_chord_root(value: str) -> tuple[str, int] | None:
    text = str(value or "").strip().replace("♯", "#").replace("♭", "b")
    if not text:
        return None
    m = re.match(r"^([A-Ga-g])([#b]?)(?:.*)$", text)
    if not m:
        return None
    step = m.group(1).upper()
    accidental = m.group(2)
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


def _build_summary_pdf(score: Score) -> bytes:
    score_data = score.score_data if isinstance(score.score_data, dict) else {}
    meta = score_data.get("meta") if isinstance(score_data.get("meta"), dict) else {}
    measures = score_data.get("measures") if isinstance(score_data.get("measures"), list) else []
    notes_count = 0
    for measure in measures:
        if isinstance(measure, dict) and isinstance(measure.get("notes"), list):
            notes_count += len(measure["notes"])

    lines = [
        "SunoScribe Score Export",
        f"Score ID: {score.id}",
        f"Project ID: {score.project_id}",
        f"Key: {meta.get('key', score.key)}",
        f"BPM: {meta.get('bpm', score_data.get('bpm', 'N/A'))}",
        f"Measures: {len(measures)}",
        f"Notes: {notes_count}",
    ]
    return _build_text_pdf(lines)


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
