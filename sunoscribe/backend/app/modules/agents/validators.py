from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from app.modules.pitch.note_utils import midi_to_note
from app.services.patch_validator import PatchValidator
from app.utils.errors import ValidationAppError

from .types import (
    AdjustDurationOperation,
    AgentRevisionContext,
    AgentScorePatch,
    DeleteNotePatchOperation,
    MarkUncertainOperation,
    MergeNotesPatchOperation,
    MoveNoteToGridOperation,
    ReplacePitchOperation,
    RvcJobSpec,
    ShiftOctaveOperation,
    SplitNoteOperation,
)


@dataclass(slots=True)
class AgentPatchValidationResult:
    score_ir: dict[str, Any]
    score_data: dict[str, Any]
    patch_data: dict[str, Any]
    diff_summary: dict[str, Any]


@dataclass(slots=True)
class RvcSpecValidationResult:
    accepted: bool
    errors: list[str]


class AgentScorePatchValidator:
    """Validate and apply agent patch proposals against an existing ScoreRevision."""

    def __init__(self) -> None:
        self._patch_validator = PatchValidator()

    def validate(self, *, context: AgentRevisionContext, proposal: AgentScorePatch | dict[str, Any]) -> dict[str, Any]:
        score_patch = proposal if isinstance(proposal, AgentScorePatch) else AgentScorePatch.model_validate(proposal)
        try:
            self._validate_only(context=context, proposal=score_patch)
        except ValidationAppError as exc:
            return {"accepted": False, "errors": [exc.message]}
        return {"accepted": True, "errors": []}

    def validate_and_apply(
        self,
        *,
        context: AgentRevisionContext,
        proposal: AgentScorePatch | dict[str, Any],
    ) -> AgentPatchValidationResult:
        score_patch = proposal if isinstance(proposal, AgentScorePatch) else AgentScorePatch.model_validate(proposal)
        self._validate_only(context=context, proposal=score_patch)

        original_score_ir = deepcopy(context.score_ir)
        working_score_ir = deepcopy(context.score_ir)
        if not isinstance(working_score_ir, dict):
            raise ValidationAppError("context score_ir is missing")

        note_by_id = self._patch_validator._note_index(working_score_ir)
        for operation in score_patch.operations:
            if isinstance(operation, ReplacePitchOperation):
                note = self._patch_validator._require_note(note_by_id, operation.note_id)
                note["pitch_midi"] = int(operation.pitch_midi)
                note["pitch"] = str(midi_to_note(operation.pitch_midi))
            elif isinstance(operation, ShiftOctaveOperation):
                note = self._patch_validator._require_note(note_by_id, operation.note_id)
                current_pitch = self._safe_pitch_midi(note)
                target_pitch = current_pitch + (int(operation.octaves) * 12)
                if target_pitch < 0 or target_pitch > 127:
                    raise ValidationAppError(f"shift_octave moves note {operation.note_id} outside MIDI range")
                note["pitch_midi"] = target_pitch
                note["pitch"] = str(midi_to_note(target_pitch))
            elif isinstance(operation, MergeNotesPatchOperation):
                self._merge_notes(working_score_ir, note_by_id, operation)
            elif isinstance(operation, SplitNoteOperation):
                self._split_note(working_score_ir, note_by_id, operation)
            elif isinstance(operation, DeleteNotePatchOperation):
                self._delete_note(working_score_ir, note_by_id, operation.note_id)
            elif isinstance(operation, AdjustDurationOperation):
                self._adjust_duration(note_by_id, operation)
            elif isinstance(operation, MoveNoteToGridOperation):
                self._move_note_to_grid(working_score_ir, note_by_id, context, operation)
            elif isinstance(operation, MarkUncertainOperation):
                self._mark_uncertain(note_by_id, operation)
            else:
                raise ValidationAppError(f"unsupported agent patch operation: {type(operation).__name__}")

            note_by_id = self._patch_validator._note_index(working_score_ir)

        self._patch_validator._validate_exportability(working_score_ir)
        rebuilt_score_data = self._patch_validator._build_score_data_from_score_ir(
            working_score_ir,
            score_data={"score_ir": deepcopy(working_score_ir)},
        )
        return AgentPatchValidationResult(
            score_ir=working_score_ir,
            score_data=rebuilt_score_data,
            patch_data=score_patch.model_dump(),
            diff_summary=self._build_diff_summary(original_score_ir, working_score_ir, score_patch),
        )

    def _validate_only(self, *, context: AgentRevisionContext, proposal: AgentScorePatch) -> None:
        if proposal.base_revision_id != context.revision_id:
            raise ValidationAppError("agent patch base_revision_id does not match loaded revision context")
        if not isinstance(context.score_ir.get("notes"), list) or not context.score_ir.get("notes"):
            raise ValidationAppError("revision score_ir has no notes")

        note_by_id = self._patch_validator._note_index(context.score_ir)
        for operation in proposal.operations:
            if isinstance(
                operation,
                (
                    ReplacePitchOperation,
                    ShiftOctaveOperation,
                    SplitNoteOperation,
                    DeleteNotePatchOperation,
                    AdjustDurationOperation,
                    MoveNoteToGridOperation,
                    MarkUncertainOperation,
                ),
            ):
                self._patch_validator._require_note(note_by_id, operation.note_id)
            elif isinstance(operation, MergeNotesPatchOperation):
                notes = [self._patch_validator._require_note(note_by_id, note_id) for note_id in operation.note_ids]
                measure_ids = {self._patch_validator._measure_identity(note) for note in notes}
                if None in measure_ids or len(measure_ids) != 1:
                    raise ValidationAppError("merge_notes cannot cross measure boundaries")

            if isinstance(operation, MoveNoteToGridOperation) and context.rhythm_grid is None:
                raise ValidationAppError("move_note_to_grid requires RhythmGrid in agent context")

    def _merge_notes(
        self,
        score_ir: dict[str, Any],
        note_by_id: dict[str, dict[str, Any]],
        operation: MergeNotesPatchOperation,
    ) -> None:
        notes = [self._patch_validator._require_note(note_by_id, note_id) for note_id in operation.note_ids]
        sorted_notes = sorted(notes, key=lambda item: self._safe_float(item.get("start_time"), 0.0))
        base = sorted_notes[0]
        reference_pitch = self._safe_pitch_midi(base)
        reference_measure = self._patch_validator._measure_identity(base)

        for note in sorted_notes[1:]:
            if self._safe_pitch_midi(note) != reference_pitch:
                raise ValidationAppError("merge_notes requires all notes to share the same pitch")
            if self._patch_validator._measure_identity(note) != reference_measure:
                raise ValidationAppError("merge_notes cannot cross measure boundaries")

        base_start = min(self._safe_float(note.get("start_time"), 0.0) for note in sorted_notes)
        base_end = max(self._safe_float(note.get("end_time"), 0.0) for note in sorted_notes)
        base["start_time"] = base_start
        base["end_time"] = base_end
        base["duration_sec"] = round(base_end - base_start, 6)

        if all(note.get("duration_beats") is not None for note in sorted_notes):
            total_beats = sum(float(note.get("duration_beats")) for note in sorted_notes)
            base["duration_beats"] = round(total_beats, 6)

        notes_list = score_ir.get("notes") or []
        consumed_ids = {str(note.get("id")) for note in sorted_notes[1:]}
        score_ir["notes"] = [note for note in notes_list if str(note.get("id")) not in consumed_ids]

    def _split_note(
        self,
        score_ir: dict[str, Any],
        note_by_id: dict[str, dict[str, Any]],
        operation: SplitNoteOperation,
    ) -> None:
        note = self._patch_validator._require_note(note_by_id, operation.note_id)
        start_time = self._safe_float(note.get("start_time"), -1.0)
        end_time = self._safe_float(note.get("end_time"), -1.0)
        if start_time < 0 or end_time <= start_time:
            raise ValidationAppError(f"note {operation.note_id} has invalid timing")

        split_at = operation.split_at_time
        if split_at is None:
            split_at = start_time + ((end_time - start_time) * float(operation.split_ratio or 0.0))
        split_time = float(split_at)
        if split_time <= start_time or split_time >= end_time:
            raise ValidationAppError("split_note split point must lie strictly inside the note duration")

        total_duration_sec = end_time - start_time
        left_duration_sec = split_time - start_time
        right_duration_sec = end_time - split_time
        if left_duration_sec <= 0 or right_duration_sec <= 0:
            raise ValidationAppError("split_note produced non-positive durations")

        new_note = deepcopy(note)
        new_note["id"] = self._next_split_id(score_ir, str(note.get("id") or "note"))
        new_note["start_time"] = split_time
        new_note["end_time"] = end_time
        new_note["duration_sec"] = round(right_duration_sec, 6)
        note["end_time"] = split_time
        note["duration_sec"] = round(left_duration_sec, 6)

        if note.get("duration_beats") is not None:
            total_beats = float(note.get("duration_beats"))
            left_beats = total_beats * (left_duration_sec / total_duration_sec)
            right_beats = total_beats - left_beats
            note["duration_beats"] = round(left_beats, 6)
            new_note["duration_beats"] = round(right_beats, 6)

        notes = [item for item in score_ir.get("notes") or [] if isinstance(item, dict)]
        notes.append(new_note)
        score_ir["notes"] = sorted(notes, key=lambda item: (self._safe_float(item.get("start_time"), 0.0), str(item.get("id"))))

    def _delete_note(self, score_ir: dict[str, Any], note_by_id: dict[str, dict[str, Any]], note_id: str) -> None:
        note = self._patch_validator._require_note(note_by_id, note_id)
        score_ir["notes"] = [item for item in score_ir.get("notes") or [] if item is not note]

    def _adjust_duration(
        self,
        note_by_id: dict[str, dict[str, Any]],
        operation: AdjustDurationOperation,
    ) -> None:
        note = self._patch_validator._require_note(note_by_id, operation.note_id)
        start_time = self._safe_float(note.get("start_time"), -1.0)
        if start_time < 0:
            raise ValidationAppError(f"note {operation.note_id} is missing start_time")

        old_duration_sec = self._safe_float(note.get("duration_sec"), 0.0)
        if operation.duration_sec is not None:
            new_duration_sec = float(operation.duration_sec)
        elif operation.duration_beats is not None and note.get("duration_beats") is not None:
            old_duration_beats = float(note.get("duration_beats"))
            if old_duration_beats <= 0 or old_duration_sec <= 0:
                raise ValidationAppError(f"note {operation.note_id} cannot derive duration_sec from duration_beats")
            new_duration_sec = old_duration_sec * (float(operation.duration_beats) / old_duration_beats)
        else:
            raise ValidationAppError("adjust_duration requires duration_sec or derivable duration_beats")

        note["end_time"] = start_time + new_duration_sec
        note["duration_sec"] = round(new_duration_sec, 6)

        if operation.duration_beats is not None:
            note["duration_beats"] = round(float(operation.duration_beats), 6)
        elif note.get("duration_beats") is not None and old_duration_sec > 0:
            scaled_beats = float(note.get("duration_beats")) * (new_duration_sec / old_duration_sec)
            note["duration_beats"] = round(scaled_beats, 6)

    def _move_note_to_grid(
        self,
        score_ir: dict[str, Any],
        note_by_id: dict[str, dict[str, Any]],
        context: AgentRevisionContext,
        operation: MoveNoteToGridOperation,
    ) -> None:
        note = self._patch_validator._require_note(note_by_id, operation.note_id)
        measures = [measure for measure in score_ir.get("measures") or [] if isinstance(measure, dict)]
        if not measures:
            raise ValidationAppError("score_ir is missing measures for move_note_to_grid")

        beats_per_bar = self._beats_per_bar(score_ir, context.rhythm_grid)
        measure_num = int(operation.measure_num or note.get("measure_num") or 0)
        if measure_num <= 0:
            raise ValidationAppError("move_note_to_grid requires an explicit or inferable measure number")
        target_measure = next(
            (measure for measure in measures if self._safe_int(measure.get("measure_num"), 0) == measure_num),
            None,
        )
        if target_measure is None:
            raise ValidationAppError(f"move_note_to_grid references missing measure {measure_num}")

        measure_start = self._safe_float(target_measure.get("start_time"), -1.0)
        measure_end = self._safe_float(target_measure.get("end_time"), -1.0)
        if measure_start < 0 or measure_end <= measure_start:
            raise ValidationAppError(f"measure {measure_num} has invalid timing")

        beat_duration = (measure_end - measure_start) / max(1, beats_per_bar)
        target_start = measure_start + ((float(operation.beat_position) - 1.0) * beat_duration)
        current_duration = self._safe_float(note.get("duration_sec"), 0.0)
        target_end = target_start + current_duration if operation.preserve_duration else self._safe_float(note.get("end_time"), target_start)
        if target_end > (measure_end + 1e-6):
            raise ValidationAppError("move_note_to_grid would push the note across a measure boundary")

        note["start_time"] = round(target_start, 6)
        note["end_time"] = round(target_end, 6)
        note["duration_sec"] = round(target_end - target_start, 6)
        note["measure_num"] = measure_num
        note["beat_position"] = round(float(operation.beat_position), 6)

    def _mark_uncertain(self, note_by_id: dict[str, dict[str, Any]], operation: MarkUncertainOperation) -> None:
        note = self._patch_validator._require_note(note_by_id, operation.note_id)
        note["uncertain"] = True
        reason_codes = list(note.get("reason_codes") or [])
        if "uncertain" not in reason_codes:
            reason_codes.append("uncertain")
        note["reason_codes"] = reason_codes
        metadata = dict(note.get("agent_metadata") or {})
        metadata["uncertain"] = True
        if operation.reason:
            metadata["reason"] = operation.reason
        note["agent_metadata"] = metadata

    def _build_diff_summary(
        self,
        before_score_ir: dict[str, Any],
        after_score_ir: dict[str, Any],
        score_patch: AgentScorePatch,
    ) -> dict[str, Any]:
        before_notes = self._patch_validator._note_index(before_score_ir)
        after_notes = self._patch_validator._note_index(after_score_ir)
        before_ids = set(before_notes)
        after_ids = set(after_notes)
        changed_note_ids: list[str] = []
        for note_id in sorted(before_ids & after_ids):
            if before_notes[note_id] != after_notes[note_id]:
                changed_note_ids.append(note_id)
        return {
            "operation_count": len(score_patch.operations),
            "operations": [operation.op for operation in score_patch.operations],
            "changed_note_ids": changed_note_ids,
            "added_note_ids": sorted(after_ids - before_ids),
            "deleted_note_ids": sorted(before_ids - after_ids),
            "note_count_before": len(before_ids),
            "note_count_after": len(after_ids),
        }

    def _next_split_id(self, score_ir: dict[str, Any], base_note_id: str) -> str:
        existing = {
            str(note.get("id"))
            for note in score_ir.get("notes") or []
            if isinstance(note, dict) and str(note.get("id") or "").strip()
        }
        suffix = 1
        while True:
            candidate = f"{base_note_id}__split{suffix}"
            if candidate not in existing:
                return candidate
            suffix += 1

    def _beats_per_bar(self, score_ir: dict[str, Any], rhythm_grid: dict[str, Any] | None) -> int:
        if isinstance(rhythm_grid, dict):
            beats = self._safe_int(rhythm_grid.get("beats_per_bar"), 0)
            if beats > 0:
                return beats
        meta = score_ir.get("meta") if isinstance(score_ir.get("meta"), dict) else {}
        time_signature = str(meta.get("time_signature") or "4/4")
        if "/" in time_signature:
            beats_text, _ = time_signature.split("/", 1)
            beats = self._safe_int(beats_text, 4)
            if beats > 0:
                return beats
        return 4

    def _safe_pitch_midi(self, note: dict[str, Any]) -> int:
        pitch_midi = self._patch_validator._safe_int(note.get("pitch_midi"), fallback=-1)
        if pitch_midi < 0 or pitch_midi > 127:
            raise ValidationAppError(f"note {note.get('id')} has invalid pitch_midi")
        return pitch_midi

    def _safe_float(self, value: Any, fallback: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return fallback

    def _safe_int(self, value: Any, fallback: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback


class RvcSpecValidator:
    def validate(self, *, context: AgentRevisionContext, spec: RvcJobSpec | dict[str, Any]) -> RvcSpecValidationResult:
        job_spec = spec if isinstance(spec, RvcJobSpec) else RvcJobSpec.model_validate(spec)
        errors: list[str] = []

        if job_spec.project_id != context.project_id:
            errors.append("project_id does not match loaded agent context")
        if job_spec.revision_id != context.revision_id:
            errors.append("revision_id does not match loaded agent context")
        if not str(job_spec.voice_model_id or "").strip():
            errors.append("voice_model_id is required")

        artifact_by_id = {artifact.id: artifact for artifact in context.artifacts}
        artifact_expectations = (
            ("vocal_stem_artifact_id", job_spec.vocal_stem_artifact_id, "vocals_stem"),
            ("accompaniment_artifact_id", job_spec.accompaniment_artifact_id, "accompaniment_stem"),
            ("corrected_f0_artifact_id", job_spec.corrected_f0_artifact_id, "corrected_f0_track"),
        )
        for field_name, artifact_id, expected_type in artifact_expectations:
            if not artifact_id:
                errors.append(f"{field_name} is required")
                continue
            artifact = artifact_by_id.get(str(artifact_id))
            if artifact is None:
                errors.append(f"{field_name} does not reference an artifact in the loaded context")
                continue
            if str(artifact.artifact_type or "").strip().lower() != expected_type:
                errors.append(f"{field_name} must reference a {expected_type} artifact")

        return RvcSpecValidationResult(accepted=not errors, errors=errors)


def validate_score_patch(*, context: AgentRevisionContext, proposal: AgentScorePatch | dict[str, Any]) -> dict[str, Any]:
    return AgentScorePatchValidator().validate(context=context, proposal=proposal)


def validate_rvc_spec(*, context: AgentRevisionContext, spec: RvcJobSpec | dict[str, Any]) -> RvcSpecValidationResult:
    return RvcSpecValidator().validate(context=context, spec=spec)
