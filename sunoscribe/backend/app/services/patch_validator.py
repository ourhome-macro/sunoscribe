from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from app.modules.pitch.note_utils import midi_to_note
from app.schemas.score_patch import (
    AdjustNoteDurationOperation,
    AdjustNoteTimingOperation,
    BindLyricTokenOperation,
    DeleteNoteOperation,
    MergeNotesOperation,
    ReplaceNotePitchOperation,
    ScorePatch,
)
from app.utils.errors import ValidationAppError


_MEASURE_EPSILON = 1e-6


@dataclass(slots=True)
class PatchValidationResult:
    score_ir: dict[str, Any]
    score_data: dict[str, Any]


class PatchValidator:
    """Validate and apply narrow score patch operations to ScoreIR."""

    def validate_score_patch(self, *, score_ir: dict[str, Any], patch: ScorePatch | dict[str, Any]) -> dict[str, Any]:
        score_patch = patch if isinstance(patch, ScorePatch) else ScorePatch.model_validate(patch)
        note_by_id = self._note_index(score_ir)
        lyric_token_text = self._lyric_token_index(score_ir)

        for operation in score_patch.operations:
            if isinstance(operation, ReplaceNotePitchOperation):
                self._require_note(note_by_id, operation.note_id)
            elif isinstance(operation, AdjustNoteTimingOperation):
                self._require_note(note_by_id, operation.note_id)
            elif isinstance(operation, AdjustNoteDurationOperation):
                self._require_note(note_by_id, operation.note_id)
            elif isinstance(operation, DeleteNoteOperation):
                self._require_note(note_by_id, operation.note_id)
            elif isinstance(operation, MergeNotesOperation):
                notes = [self._require_note(note_by_id, note_id) for note_id in operation.note_ids]
                measure_ids = {self._measure_identity(note) for note in notes}
                if None in measure_ids or len(measure_ids) != 1:
                    raise ValidationAppError("merge_notes cannot cross measure boundaries")
            elif isinstance(operation, BindLyricTokenOperation):
                self._require_note(note_by_id, operation.note_id)
                if operation.lyric_token_id not in lyric_token_text:
                    raise ValidationAppError(f"patch references missing lyric token id: {operation.lyric_token_id}")

        return {"accepted": True, "errors": []}

    def validate_patch(self, *, score_ir: dict[str, Any], patch: ScorePatch | dict[str, Any]) -> dict[str, Any]:
        return self.validate_score_patch(score_ir=score_ir, patch=patch)

    def validate(self, *, score_ir: dict[str, Any], patch: ScorePatch | dict[str, Any]) -> dict[str, Any]:
        return self.validate_score_patch(score_ir=score_ir, patch=patch)

    def validate_and_apply(
        self,
        *,
        score_ir: dict[str, Any],
        score_data: dict[str, Any] | None,
        patch: ScorePatch,
    ) -> PatchValidationResult:
        self.validate_score_patch(score_ir=score_ir, patch=patch)
        if not isinstance(score_ir, dict) or not isinstance(score_ir.get("notes"), list):
            raise ValidationAppError("score revision is missing canonical score_ir notes")

        working_score_ir = deepcopy(score_ir)
        note_by_id = self._note_index(working_score_ir)
        lyric_token_text = self._lyric_token_index(working_score_ir)

        for operation in patch.operations:
            if isinstance(operation, ReplaceNotePitchOperation):
                self._replace_note_pitch(note_by_id, operation)
            elif isinstance(operation, AdjustNoteTimingOperation):
                self._adjust_note_timing(note_by_id, operation)
            elif isinstance(operation, AdjustNoteDurationOperation):
                self._adjust_note_duration(note_by_id, operation)
            elif isinstance(operation, DeleteNoteOperation):
                self._delete_note(working_score_ir, note_by_id, operation)
            elif isinstance(operation, MergeNotesOperation):
                self._merge_notes(working_score_ir, note_by_id, operation)
            elif isinstance(operation, BindLyricTokenOperation):
                self._bind_lyric_token(note_by_id, lyric_token_text, operation)
            else:
                raise ValidationAppError(f"unsupported patch operation: {type(operation).__name__}")

            note_by_id = self._note_index(working_score_ir)

        self._validate_exportability(working_score_ir)
        patched_score_data = self._build_score_data_from_score_ir(
            working_score_ir,
            score_data=deepcopy(score_data) if isinstance(score_data, dict) else {},
        )
        return PatchValidationResult(score_ir=working_score_ir, score_data=patched_score_data)

    def _note_index(self, score_ir: dict[str, Any]) -> dict[str, dict[str, Any]]:
        notes = score_ir.get("notes")
        if not isinstance(notes, list):
            raise ValidationAppError("score_ir.notes must be a list")

        index: dict[str, dict[str, Any]] = {}
        for note in notes:
            if not isinstance(note, dict):
                raise ValidationAppError("score_ir.notes contains non-object entries")
            note_id = str(note.get("id") or "").strip()
            if not note_id:
                raise ValidationAppError("score_ir note is missing id")
            if note_id in index:
                raise ValidationAppError(f"score_ir contains duplicate note id: {note_id}")
            index[note_id] = note
        return index

    def _lyric_token_index(self, score_ir: dict[str, Any]) -> dict[str, str]:
        index: dict[str, str] = {}
        for token in score_ir.get("lyrics_tokens") or []:
            if not isinstance(token, dict):
                continue
            token_id = str(token.get("id") or "").strip()
            token_text = str(token.get("text") or "").strip()
            if token_id:
                index[token_id] = token_text
        for segment in score_ir.get("lyrics_segments") or []:
            if not isinstance(segment, dict):
                continue
            for token in segment.get("tokens") or []:
                if not isinstance(token, dict):
                    continue
                token_id = str(token.get("id") or "").strip()
                token_text = str(token.get("text") or "").strip()
                if token_id:
                    index[token_id] = token_text
        return index

    def _require_note(self, note_by_id: dict[str, dict[str, Any]], note_id: str) -> dict[str, Any]:
        note = note_by_id.get(str(note_id).strip())
        if note is None:
            raise ValidationAppError(f"patch references missing note id: {note_id}")
        return note

    def _replace_note_pitch(
        self,
        note_by_id: dict[str, dict[str, Any]],
        operation: ReplaceNotePitchOperation,
    ) -> None:
        note = self._require_note(note_by_id, operation.note_id)
        note["pitch_midi"] = int(operation.pitch_midi)
        note["pitch"] = str(midi_to_note(operation.pitch_midi))

    def _adjust_note_timing(
        self,
        note_by_id: dict[str, dict[str, Any]],
        operation: AdjustNoteTimingOperation,
    ) -> None:
        note = self._require_note(note_by_id, operation.note_id)
        old_duration_sec = self._safe_float(note.get("duration_sec"), fallback=0.0)
        new_duration_sec = float(operation.end_time) - float(operation.start_time)
        if new_duration_sec <= 0:
            raise ValidationAppError("patch operation produced non-positive duration")

        note["start_time"] = float(operation.start_time)
        note["end_time"] = float(operation.end_time)
        note["duration_sec"] = new_duration_sec

        old_duration_beats = note.get("duration_beats")
        if old_duration_beats is not None and old_duration_sec > 0:
            scaled_beats = float(old_duration_beats) * (new_duration_sec / old_duration_sec)
            note["duration_beats"] = round(scaled_beats, 6)
            note["note_type"] = self._infer_note_type(note["duration_beats"])

    def _adjust_note_duration(
        self,
        note_by_id: dict[str, dict[str, Any]],
        operation: AdjustNoteDurationOperation,
    ) -> None:
        note = self._require_note(note_by_id, operation.note_id)
        start_time = self._safe_float(note.get("start_time"), fallback=-1.0)
        if start_time < 0:
            raise ValidationAppError(f"note {operation.note_id} is missing start_time")

        old_duration_sec = self._safe_float(note.get("duration_sec"), fallback=0.0)
        if operation.duration_sec is not None:
            new_duration_sec = float(operation.duration_sec)
        elif operation.duration_beats is not None and note.get("duration_beats") is not None:
            old_duration_beats = float(note["duration_beats"])
            if old_duration_beats <= 0 or old_duration_sec <= 0:
                raise ValidationAppError(f"note {operation.note_id} cannot derive duration_sec from duration_beats")
            new_duration_sec = old_duration_sec * (float(operation.duration_beats) / old_duration_beats)
        else:
            raise ValidationAppError("adjust_note_duration requires duration_sec or derivable duration_beats")
        note["end_time"] = start_time + new_duration_sec
        note["duration_sec"] = new_duration_sec

        if operation.duration_beats is not None:
            note["duration_beats"] = round(float(operation.duration_beats), 6)
        elif note.get("duration_beats") is not None and old_duration_sec > 0:
            scaled_beats = float(note["duration_beats"]) * (new_duration_sec / old_duration_sec)
            note["duration_beats"] = round(scaled_beats, 6)

        if note.get("duration_beats") is not None:
            note["note_type"] = self._infer_note_type(float(note["duration_beats"]))

    def _delete_note(
        self,
        score_ir: dict[str, Any],
        note_by_id: dict[str, dict[str, Any]],
        operation: DeleteNoteOperation,
    ) -> None:
        note = self._require_note(note_by_id, operation.note_id)
        notes = score_ir.get("notes") or []
        score_ir["notes"] = [item for item in notes if item is not note]

    def _merge_notes(
        self,
        score_ir: dict[str, Any],
        note_by_id: dict[str, dict[str, Any]],
        operation: MergeNotesOperation,
    ) -> None:
        notes = [self._require_note(note_by_id, note_id) for note_id in operation.note_ids]
        sorted_notes = sorted(notes, key=lambda item: self._safe_float(item.get("start_time"), fallback=0.0))
        base_note = sorted_notes[0]
        reference_pitch = self._pitch_identity(base_note)
        reference_measure = self._measure_identity(base_note)

        for note in sorted_notes[1:]:
            if self._pitch_identity(note) != reference_pitch:
                raise ValidationAppError("merge_notes requires all notes to share the same pitch")
            if self._measure_identity(note) != reference_measure:
                raise ValidationAppError("merge_notes cannot cross measure boundaries")

        base_note["start_time"] = min(self._safe_float(note.get("start_time"), fallback=0.0) for note in sorted_notes)
        base_note["end_time"] = max(self._safe_float(note.get("end_time"), fallback=0.0) for note in sorted_notes)
        base_note["duration_sec"] = round(base_note["end_time"] - base_note["start_time"], 6)

        merged_duration_beats = 0.0
        has_duration_beats = True
        for note in sorted_notes:
            duration_beats = note.get("duration_beats")
            if duration_beats is None:
                has_duration_beats = False
                break
            merged_duration_beats += float(duration_beats)
        if has_duration_beats:
            base_note["duration_beats"] = round(merged_duration_beats, 6)
            base_note["note_type"] = self._infer_note_type(base_note["duration_beats"])

        notes_list = score_ir.get("notes") or []
        consumed_ids = {str(note.get("id")) for note in sorted_notes[1:]}
        score_ir["notes"] = [note for note in notes_list if str(note.get("id")) not in consumed_ids]

    def _bind_lyric_token(
        self,
        note_by_id: dict[str, dict[str, Any]],
        lyric_token_text: dict[str, str],
        operation: BindLyricTokenOperation,
    ) -> None:
        note = self._require_note(note_by_id, operation.note_id)
        token_text = lyric_token_text.get(operation.lyric_token_id)
        if token_text is None:
            raise ValidationAppError(f"patch references missing lyric token id: {operation.lyric_token_id}")
        note["lyric"] = token_text

    def _validate_exportability(self, score_ir: dict[str, Any]) -> None:
        notes = score_ir.get("notes")
        measures = score_ir.get("measures")
        if not isinstance(notes, list) or not notes:
            raise ValidationAppError("patched score would contain no notes")
        if not isinstance(measures, list) or not measures:
            raise ValidationAppError("patched score is missing measures")

        beats_per_bar = self._parse_beats_per_bar(score_ir)
        notes.sort(key=lambda note: (self._safe_float(note.get("start_time"), fallback=0.0), str(note.get("id"))))

        for measure in measures:
            if not isinstance(measure, dict):
                raise ValidationAppError("score_ir.measures contains non-object entries")
            measure["note_ids"] = []

        ordered_measures = sorted(
            [measure for measure in measures if isinstance(measure, dict)],
            key=lambda item: self._safe_int(item.get("measure_num"), fallback=0),
        )
        if not ordered_measures:
            raise ValidationAppError("patched score is missing ordered measures")

        for expected_idx, measure in enumerate(ordered_measures, start=1):
            measure_num = self._safe_int(measure.get("measure_num"), fallback=0)
            if measure_num != expected_idx:
                raise ValidationAppError("patched score has non-sequential measures")
            measure_start = self._safe_float(measure.get("start_time"), fallback=-1.0)
            measure_end = self._safe_float(measure.get("end_time"), fallback=-1.0)
            if measure_start < 0 or measure_end <= measure_start:
                raise ValidationAppError(f"measure {measure_num} has invalid time bounds")

        for note in notes:
            self._validate_note_fields(note)
            note_measure = self._assign_note_to_measure(note, ordered_measures, beats_per_bar)
            note_measure["note_ids"].append(str(note["id"]))

        score_ir["measures"] = ordered_measures

    def _validate_note_fields(self, note: dict[str, Any]) -> None:
        start_time = self._safe_float(note.get("start_time"), fallback=-1.0)
        end_time = self._safe_float(note.get("end_time"), fallback=-1.0)
        duration_sec = self._safe_float(note.get("duration_sec"), fallback=-1.0)
        if start_time < 0 or end_time <= start_time or duration_sec <= 0:
            raise ValidationAppError(f"note {note.get('id')} has invalid timing")

        pitch_midi = note.get("pitch_midi")
        if pitch_midi is not None:
            midi_num = self._safe_int(pitch_midi, fallback=-1)
            if midi_num < 0 or midi_num > 127:
                raise ValidationAppError(f"note {note.get('id')} has invalid pitch_midi")
            note["pitch_midi"] = midi_num
            note["pitch"] = str(midi_to_note(midi_num))

        duration_beats = note.get("duration_beats")
        if duration_beats is not None and float(duration_beats) <= 0:
            raise ValidationAppError(f"note {note.get('id')} has non-positive duration_beats")

    def _assign_note_to_measure(
        self,
        note: dict[str, Any],
        ordered_measures: list[dict[str, Any]],
        beats_per_bar: int,
    ) -> dict[str, Any]:
        note_id = str(note.get("id"))
        note_start = self._safe_float(note.get("start_time"), fallback=-1.0)
        note_end = self._safe_float(note.get("end_time"), fallback=-1.0)

        selected_measure: dict[str, Any] | None = None
        for idx, measure in enumerate(ordered_measures):
            measure_start = self._safe_float(measure.get("start_time"), fallback=-1.0)
            measure_end = self._safe_float(measure.get("end_time"), fallback=-1.0)
            is_last_measure = idx == len(ordered_measures) - 1
            if note_start + _MEASURE_EPSILON < measure_start:
                continue
            if note_start < measure_end - _MEASURE_EPSILON or (is_last_measure and note_start <= measure_end + _MEASURE_EPSILON):
                selected_measure = measure
                break

        if selected_measure is None:
            raise ValidationAppError(f"note {note_id} falls outside all measures")

        measure_end = self._safe_float(selected_measure.get("end_time"), fallback=-1.0)
        if note_end > measure_end + _MEASURE_EPSILON:
            raise ValidationAppError(f"note {note_id} crosses a measure boundary")

        measure_num = self._safe_int(selected_measure.get("measure_num"), fallback=0)
        measure_start = self._safe_float(selected_measure.get("start_time"), fallback=0.0)
        bar_duration = max(measure_end - measure_start, _MEASURE_EPSILON)
        beat_duration = bar_duration / max(1, beats_per_bar)
        note["measure_num"] = measure_num
        note["beat_position"] = round(1.0 + (note_start - measure_start) / beat_duration, 6)
        if note.get("duration_beats") is None:
            note["duration_beats"] = round((note_end - note_start) / beat_duration, 6)
        note["note_type"] = self._infer_note_type(float(note["duration_beats"]))
        return selected_measure

    def _build_score_data_from_score_ir(
        self,
        score_ir: dict[str, Any],
        *,
        score_data: dict[str, Any],
    ) -> dict[str, Any]:
        note_by_id = {
            str(note.get("id")): note
            for note in score_ir.get("notes") or []
            if isinstance(note, dict) and str(note.get("id") or "").strip()
        }
        packed_measures: list[dict[str, Any]] = []
        for measure in score_ir.get("measures") or []:
            if not isinstance(measure, dict):
                continue
            packed_notes: list[dict[str, Any]] = []
            for note_id in measure.get("note_ids") or []:
                note = note_by_id.get(str(note_id))
                if note is None:
                    raise ValidationAppError(f"measure references missing note id: {note_id}")
                packed_notes.append(
                    {
                        "id": note["id"],
                        "pitch": note.get("pitch"),
                        "pitch_midi": note.get("pitch_midi"),
                        "start_time": note.get("start_time"),
                        "end_time": note.get("end_time"),
                        "duration_beats": note.get("duration_beats"),
                        "note_type": note.get("note_type"),
                        "beat_position": note.get("beat_position"),
                        "lyric": note.get("lyric"),
                        "confidence": note.get("confidence"),
                    }
                )

            packed_measures.append(
                {
                    "measure_num": measure.get("measure_num"),
                    "start_time": measure.get("start_time"),
                    "end_time": measure.get("end_time"),
                    "is_anacrusis": bool(measure.get("is_anacrusis", False)),
                    "notes": packed_notes,
                }
            )

        meta = score_data.get("meta")
        merged_meta = dict(meta) if isinstance(meta, dict) else {}
        score_ir_meta = score_ir.get("meta")
        if isinstance(score_ir_meta, dict):
            merged_meta.update(score_ir_meta)

        updated_score_data = dict(score_data)
        updated_score_data["meta"] = merged_meta
        updated_score_data["bpm"] = merged_meta.get("bpm")
        updated_score_data["key"] = merged_meta.get("key")
        updated_score_data["time_signature"] = merged_meta.get("time_signature")
        updated_score_data["measures"] = packed_measures
        updated_score_data["score_ir"] = deepcopy(score_ir)
        updated_score_data["chord_timeline"] = deepcopy(score_ir.get("chord_timeline") or [])
        updated_score_data["form_sections"] = deepcopy(score_ir.get("form_sections") or [])
        updated_score_data["lyrics_segments"] = deepcopy(score_ir.get("lyrics_segments") or [])
        updated_score_data["analysis_hints"] = deepcopy(score_ir.get("analysis_hints") or {})
        updated_score_data["warnings"] = list(score_ir.get("warnings") or [])
        return updated_score_data

    def _parse_beats_per_bar(self, score_ir: dict[str, Any]) -> int:
        meta = score_ir.get("meta")
        time_signature = "4/4"
        if isinstance(meta, dict) and meta.get("time_signature"):
            time_signature = str(meta.get("time_signature"))
        if "/" not in time_signature:
            return 4
        beats_text, _ = time_signature.split("/", 1)
        beats = self._safe_int(beats_text, fallback=4)
        return max(1, beats)

    def _pitch_identity(self, note: dict[str, Any]) -> tuple[Any, Any]:
        return note.get("pitch_midi"), str(note.get("pitch") or "")

    def _measure_identity(self, note: dict[str, Any]) -> Any:
        if note.get("measure_num") is not None:
            return note.get("measure_num")
        if note.get("measure_id") is not None:
            return note.get("measure_id")
        return None

    def _infer_note_type(self, duration_beats: float) -> str:
        if duration_beats >= 3.5:
            return "whole"
        if duration_beats >= 1.75:
            return "half"
        if duration_beats >= 1.25:
            return "dotted_quarter"
        if duration_beats >= 0.75:
            return "quarter"
        if duration_beats >= 0.5:
            return "eighth"
        if duration_beats >= 0.25:
            return "sixteenth"
        return "thirty_second"

    def _safe_float(self, value: Any, *, fallback: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return fallback

    def _safe_int(self, value: Any, *, fallback: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback
