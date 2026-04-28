from __future__ import annotations

import json
import re
from typing import Any

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
    ShiftOctaveOperation,
    SplitNoteOperation,
)


class ScorePatchAgent:
    """Deterministic instruction-to-patch converter over an existing ScoreRevision."""

    _NUMBER_PATTERN = re.compile(r"(-?\d+(?:\.\d+)?)")

    def propose(self, context: AgentRevisionContext, instruction: str | dict[str, Any] | AgentScorePatch) -> AgentScorePatch:
        if isinstance(instruction, AgentScorePatch):
            return instruction
        if isinstance(instruction, dict):
            return AgentScorePatch.model_validate(instruction)

        text = str(instruction or "").strip()
        if not text:
            raise ValidationAppError("score patch instruction cannot be empty")

        if text.startswith("{") and text.endswith("}"):
            try:
                return AgentScorePatch.model_validate(json.loads(text))
            except Exception as exc:
                raise ValidationAppError("invalid structured score patch instruction") from exc

        note_ids = self._extract_note_ids(context, text)
        if "合并" in text or "merge" in text.lower():
            if len(note_ids) < 2:
                raise ValidationAppError("merge instruction must reference at least two note ids")
            return AgentScorePatch(
                base_revision_id=context.revision_id,
                operations=[MergeNotesPatchOperation(op="merge_notes", note_ids=note_ids)],
                rationale="merge_notes parsed from deterministic instruction",
                confidence=0.86,
            )

        if "删除" in text or "delete" in text.lower() or "remove" in text.lower():
            note_id = self._require_single_note_id(note_ids, "delete")
            return AgentScorePatch(
                base_revision_id=context.revision_id,
                operations=[DeleteNotePatchOperation(op="delete_note", note_id=note_id)],
                rationale="delete_note parsed from deterministic instruction",
                confidence=0.9,
            )

        if "不确定" in text or "uncertain" in text.lower() or "标记" in text:
            note_id = self._require_single_note_id(note_ids, "mark_uncertain")
            return AgentScorePatch(
                base_revision_id=context.revision_id,
                operations=[MarkUncertainOperation(op="mark_uncertain", note_id=note_id)],
                rationale="mark_uncertain parsed from deterministic instruction",
                confidence=0.82,
            )

        if "升八度" in text or "octave up" in text.lower():
            note_id = self._require_single_note_id(note_ids, "shift_octave")
            return AgentScorePatch(
                base_revision_id=context.revision_id,
                operations=[ShiftOctaveOperation(op="shift_octave", note_id=note_id, octaves=1)],
                rationale="shift_octave(+1) parsed from deterministic instruction",
                confidence=0.88,
            )

        if "降八度" in text or "octave down" in text.lower():
            note_id = self._require_single_note_id(note_ids, "shift_octave")
            return AgentScorePatch(
                base_revision_id=context.revision_id,
                operations=[ShiftOctaveOperation(op="shift_octave", note_id=note_id, octaves=-1)],
                rationale="shift_octave(-1) parsed from deterministic instruction",
                confidence=0.88,
            )

        if "拆分" in text or "split" in text.lower():
            note_id = self._require_single_note_id(note_ids, "split_note")
            split_time = self._parse_time_value(text)
            split_ratio = self._parse_ratio_value(text)
            if split_time is None and split_ratio is None:
                raise ValidationAppError("split instruction must include a time in seconds or a ratio")
            return AgentScorePatch(
                base_revision_id=context.revision_id,
                operations=[
                    SplitNoteOperation(
                        op="split_note",
                        note_id=note_id,
                        split_at_time=split_time,
                        split_ratio=split_ratio,
                    )
                ],
                rationale="split_note parsed from deterministic instruction",
                confidence=0.78,
            )

        if ("时值" in text or "duration" in text.lower()) and ("拍" in text or "beat" in text.lower() or "秒" in text):
            note_id = self._require_single_note_id(note_ids, "adjust_duration")
            duration_beats = self._parse_beats_value(text)
            duration_sec = self._parse_time_value(text)
            return AgentScorePatch(
                base_revision_id=context.revision_id,
                operations=[
                    AdjustDurationOperation(
                        op="adjust_duration",
                        note_id=note_id,
                        duration_sec=duration_sec,
                        duration_beats=duration_beats,
                    )
                ],
                rationale="adjust_duration parsed from deterministic instruction",
                confidence=0.8,
            )

        if "移到" in text or "移动到" in text or "move" in text.lower():
            note_id = self._require_single_note_id(note_ids, "move_note_to_grid")
            beat_position = self._parse_beats_value(text)
            if beat_position is None:
                raise ValidationAppError("move_note_to_grid instruction must include a beat position")
            measure_num = self._parse_measure_num(text)
            return AgentScorePatch(
                base_revision_id=context.revision_id,
                operations=[
                    MoveNoteToGridOperation(
                        op="move_note_to_grid",
                        note_id=note_id,
                        beat_position=beat_position,
                        measure_num=measure_num,
                    )
                ],
                rationale="move_note_to_grid parsed from deterministic instruction",
                confidence=0.77,
            )

        if any(keyword in text for keyword in ("改成", "改为", "pitch", "音高")):
            note_id = self._require_single_note_id(note_ids, "replace_pitch")
            pitch_midi = self._parse_int_value(text)
            if pitch_midi is None:
                raise ValidationAppError("replace_pitch instruction must include a MIDI pitch number")
            return AgentScorePatch(
                base_revision_id=context.revision_id,
                operations=[ReplacePitchOperation(op="replace_pitch", note_id=note_id, pitch_midi=pitch_midi)],
                rationale="replace_pitch parsed from deterministic instruction",
                confidence=0.84,
            )

        raise ValidationAppError("instruction could not be converted into a supported structured ScorePatch")

    def _extract_note_ids(self, context: AgentRevisionContext, instruction: str) -> list[str]:
        note_ids = [
            str(note.get("id"))
            for note in context.score_ir.get("notes") or []
            if isinstance(note, dict) and str(note.get("id") or "").strip()
        ]
        found = [note_id for note_id in note_ids if note_id in instruction]
        return sorted(found, key=lambda item: instruction.index(item))

    def _require_single_note_id(self, note_ids: list[str], op_name: str) -> str:
        if len(note_ids) != 1:
            raise ValidationAppError(f"{op_name} instruction must reference exactly one note id")
        return note_ids[0]

    def _parse_int_value(self, text: str) -> int | None:
        match = self._NUMBER_PATTERN.search(text)
        if match is None:
            return None
        try:
            return int(round(float(match.group(1))))
        except (TypeError, ValueError):
            return None

    def _parse_time_value(self, text: str) -> float | None:
        match = re.search(r"(\d+(?:\.\d+)?)\s*(?:秒|sec|seconds?)", text, re.IGNORECASE)
        if match is None:
            return None
        try:
            return float(match.group(1))
        except (TypeError, ValueError):
            return None

    def _parse_ratio_value(self, text: str) -> float | None:
        match = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
        if match is None:
            return None
        try:
            return float(match.group(1)) / 100.0
        except (TypeError, ValueError):
            return None

    def _parse_beats_value(self, text: str) -> float | None:
        match = re.search(r"(\d+(?:\.\d+)?)\s*(?:拍|beats?)", text, re.IGNORECASE)
        if match is None:
            return None
        try:
            return float(match.group(1))
        except (TypeError, ValueError):
            return None

    def _parse_measure_num(self, text: str) -> int | None:
        match = re.search(r"第\s*(\d+)\s*小节", text)
        if match is None:
            match = re.search(r"measure\s*(\d+)", text, re.IGNORECASE)
        if match is None:
            return None
        try:
            return int(match.group(1))
        except (TypeError, ValueError):
            return None
