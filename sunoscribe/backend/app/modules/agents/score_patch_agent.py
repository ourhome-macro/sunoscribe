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
        lower_text = text.lower()

        if text.startswith("{") and text.endswith("}"):
            try:
                return AgentScorePatch.model_validate(json.loads(text))
            except Exception as exc:
                raise ValidationAppError("invalid structured score patch instruction") from exc

        note_ids = self._extract_note_ids(context, text)
        has_uncertain_target = "uncertain" in lower_text
        has_pitch_intent = any(keyword in lower_text for keyword in ("replace", "pitch")) or any(
            keyword in text
            for keyword in (
                "\u6539\u6210",
                "\u6539\u4e3a",
                "\u97f3\u9ad8",
                "\u93c0\u89c4\u57da",
                "\u93c0\u9036\u8d1f",
                "\u95ca\u62bd\u73ee",
            )
        )
        if not note_ids and has_uncertain_target:
            uncertain_note_id = self._first_uncertain_note_id(context)
            if uncertain_note_id:
                note_ids = [uncertain_note_id]

        if self._contains_any(text, lower_text, text_keywords=("\u5408\u5e76", "\u935a\u581d\u82df"), lower_keywords=("merge",)):
            if len(note_ids) < 2:
                raise ValidationAppError("merge instruction must reference at least two note ids")
            return AgentScorePatch(
                base_revision_id=context.revision_id,
                operations=[MergeNotesPatchOperation(op="merge_notes", note_ids=note_ids)],
                rationale="merge_notes parsed from deterministic instruction",
                confidence=0.86,
            )

        if self._contains_any(text, lower_text, text_keywords=("\u5220\u9664", "\u9352\u72b5\u6ae7"), lower_keywords=("delete", "remove")):
            note_id = self._require_single_note_id(note_ids, "delete")
            return AgentScorePatch(
                base_revision_id=context.revision_id,
                operations=[DeleteNotePatchOperation(op="delete_note", note_id=note_id)],
                rationale="delete_note parsed from deterministic instruction",
                confidence=0.9,
            )

        if self._contains_any(
            text,
            lower_text,
            text_keywords=("\u4e0d\u786e\u5b9a", "\u6807\u8bb0", "\u97f3\u9ce9\u5354", "\u708e\u829d"),
            lower_keywords=("uncertain",),
        ) and not has_pitch_intent:
            note_id = self._require_single_note_id(note_ids, "mark_uncertain")
            return AgentScorePatch(
                base_revision_id=context.revision_id,
                operations=[MarkUncertainOperation(op="mark_uncertain", note_id=note_id)],
                rationale="mark_uncertain parsed from deterministic instruction",
                confidence=0.82,
            )

        if self._contains_any(text, lower_text, text_keywords=("\u5347\u516b\u5ea6", "\u5e45\u4f0a\u696d"), lower_keywords=("octave up",)):
            note_id = self._require_single_note_id(note_ids, "shift_octave")
            return AgentScorePatch(
                base_revision_id=context.revision_id,
                operations=[ShiftOctaveOperation(op="shift_octave", note_id=note_id, octaves=1)],
                rationale="shift_octave(+1) parsed from deterministic instruction",
                confidence=0.88,
            )

        if self._contains_any(text, lower_text, text_keywords=("\u964d\u516b\u5ea6", "\u9031\u4f0a\u696d"), lower_keywords=("octave down",)):
            note_id = self._require_single_note_id(note_ids, "shift_octave")
            return AgentScorePatch(
                base_revision_id=context.revision_id,
                operations=[ShiftOctaveOperation(op="shift_octave", note_id=note_id, octaves=-1)],
                rationale="shift_octave(-1) parsed from deterministic instruction",
                confidence=0.88,
            )

        if self._contains_any(text, lower_text, text_keywords=("\u62c6\u5206", "\u9398\u55d7\u579d"), lower_keywords=("split",)):
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

        has_duration_intent = self._contains_any(
            text,
            lower_text,
            text_keywords=("\u65f6\u503c", "\u65f6\u957f", "\u93c3\u8dfa\u20ac"),
            lower_keywords=("duration",),
        )
        has_duration_unit = self._contains_any(
            text,
            lower_text,
            text_keywords=("\u62cd", "\u79d2", "\u93b7", "\u7ec9"),
            lower_keywords=("beat", "sec", "second"),
        )
        if has_duration_intent and has_duration_unit:
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

        if self._contains_any(
            text,
            lower_text,
            text_keywords=("\u79fb\u52a8\u5230", "\u79fb\u5230", "\u7ec9\u8bfb\u57cc", "\u7ec9\u8bfb\u59e9\u9352"),
            lower_keywords=("move",),
        ):
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

        if has_pitch_intent:
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

    def _first_uncertain_note_id(self, context: AgentRevisionContext) -> str | None:
        for note in context.score_ir.get("notes") or []:
            if not isinstance(note, dict):
                continue
            reason_codes = list(note.get("reason_codes") or [])
            if bool(note.get("uncertain")) or "uncertain" in reason_codes or "low_confidence" in reason_codes:
                note_id = str(note.get("id") or "").strip()
                if note_id:
                    return note_id
        return None

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
        match = re.search(r"(\d+(?:\.\d+)?)\s*(?:\u79d2|\u7ec9|sec|seconds?)", text, re.IGNORECASE)
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
        match = re.search(r"(\d+(?:\.\d+)?)\s*(?:\u62cd|\u93b7|beats?)", text, re.IGNORECASE)
        if match is None:
            return None
        try:
            return float(match.group(1))
        except (TypeError, ValueError):
            return None

    def _parse_measure_num(self, text: str) -> int | None:
        match = re.search(r"\u7b2c\s*(\d+)\s*\u5c0f\u8282", text)
        if match is None:
            match = re.search(r"measure\s*(\d+)", text, re.IGNORECASE)
        if match is None:
            return None
        try:
            return int(match.group(1))
        except (TypeError, ValueError):
            return None

    def _contains_any(
        self,
        text: str,
        lower_text: str,
        *,
        text_keywords: tuple[str, ...] = (),
        lower_keywords: tuple[str, ...] = (),
    ) -> bool:
        return any(keyword in text for keyword in text_keywords) or any(keyword in lower_text for keyword in lower_keywords)
