from __future__ import annotations

from dataclasses import dataclass
from typing import List

from .config import PitchDetectionConfig
from .note_utils import note_to_midi
from .types import Note


@dataclass
class MelodySelectionResult:
    notes: List[Note]
    detected_count: int
    kept_count: int
    removed_pitch_range: int = 0
    removed_low_confidence: int = 0
    removed_short: int = 0
    removed_conflict: int = 0
    removed_big_leap: int = 0
    merged_count: int = 0


class MelodySelector:
    """Select a conservative single-line melody from detector notes."""

    def __init__(self, config: PitchDetectionConfig | None = None) -> None:
        self.config = config or PitchDetectionConfig()

    def select(self, notes: List[Note]) -> MelodySelectionResult:
        if not notes:
            return MelodySelectionResult(notes=[], detected_count=0, kept_count=0)

        sorted_notes = sorted(notes, key=lambda n: (float(n.start_time), float(n.end_time), str(n.pitch)))
        if not bool(self.config.melody_selector_enabled):
            return MelodySelectionResult(
                notes=sorted_notes,
                detected_count=len(sorted_notes),
                kept_count=len(sorted_notes),
            )

        prepared: list[Note] = []
        removed_pitch_range = 0
        removed_low_confidence = 0
        removed_short = 0

        for note in sorted_notes:
            duration = max(0.0, float(note.end_time) - float(note.start_time))
            confidence = float(note.confidence)
            pitch_midi = self._to_midi(note.pitch)
            if pitch_midi is None:
                removed_pitch_range += 1
                continue
            if pitch_midi < int(self.config.melody_pitch_min_midi) or pitch_midi > int(self.config.melody_pitch_max_midi):
                removed_pitch_range += 1
                continue
            if duration < float(self.config.melody_min_duration_sec):
                removed_short += 1
                continue
            if confidence < float(self.config.melody_min_confidence):
                removed_low_confidence += 1
                continue
            if duration < float(self.config.melody_short_note_sec) and confidence < float(
                self.config.melody_short_note_min_confidence
            ):
                removed_low_confidence += 1
                continue

            prepared.append(
                Note(
                    pitch=str(note.pitch),
                    start_time=float(note.start_time),
                    end_time=float(note.end_time),
                    confidence=confidence,
                )
            )

        merged_notes, merged_count_a = self._merge_adjacent(prepared)
        resolved_notes, removed_conflict = self._resolve_conflicts(merged_notes)
        cleaned_notes, removed_big_leap = self._remove_isolated_big_leaps(resolved_notes)
        final_notes, merged_count_b = self._merge_adjacent(cleaned_notes)

        return MelodySelectionResult(
            notes=final_notes,
            detected_count=len(sorted_notes),
            kept_count=len(final_notes),
            removed_pitch_range=removed_pitch_range,
            removed_low_confidence=removed_low_confidence,
            removed_short=removed_short,
            removed_conflict=removed_conflict,
            removed_big_leap=removed_big_leap,
            merged_count=merged_count_a + merged_count_b,
        )

    def _merge_adjacent(self, notes: List[Note]) -> tuple[list[Note], int]:
        if not notes:
            return [], 0

        max_gap = max(0.0, float(self.config.melody_merge_gap_sec))
        max_semitone = max(0, int(self.config.melody_merge_pitch_tolerance_semitones))
        merged: list[Note] = []
        merge_count = 0

        current = notes[0]
        for nxt in notes[1:]:
            gap = float(nxt.start_time) - float(current.end_time)
            cur_midi = self._to_midi(current.pitch)
            nxt_midi = self._to_midi(nxt.pitch)
            mergeable = (
                cur_midi is not None
                and nxt_midi is not None
                and gap >= 0.0
                and gap <= max_gap
                and abs(cur_midi - nxt_midi) <= max_semitone
            )
            if mergeable:
                merge_count += 1
                current = Note(
                    pitch=current.pitch,
                    start_time=float(current.start_time),
                    end_time=max(float(current.end_time), float(nxt.end_time)),
                    confidence=max(float(current.confidence), float(nxt.confidence)),
                )
                continue

            merged.append(current)
            current = nxt

        merged.append(current)
        return merged, merge_count

    def _resolve_conflicts(self, notes: List[Note]) -> tuple[list[Note], int]:
        if len(notes) <= 1:
            return notes, 0

        window = max(0.0, float(self.config.melody_conflict_window_sec))
        result: list[Note] = []
        removed = 0
        idx = 0

        while idx < len(notes):
            anchor = float(notes[idx].start_time)
            group = [notes[idx]]
            j = idx + 1
            while j < len(notes):
                start = float(notes[j].start_time)
                if start - anchor <= window:
                    group.append(notes[j])
                    j += 1
                    continue
                if group and float(notes[j].start_time) < float(group[-1].end_time):
                    group.append(notes[j])
                    j += 1
                    continue
                break

            prev_pitch = self._to_midi(result[-1].pitch) if result else None
            winner = self._choose_best(group, prev_pitch)
            result.append(winner)
            removed += max(0, len(group) - 1)
            idx = j

        return result, removed

    def _choose_best(self, group: list[Note], prev_pitch: int | None) -> Note:
        def ranking(note: Note) -> tuple[float, float, float, float]:
            duration = max(0.0, float(note.end_time) - float(note.start_time))
            confidence = float(note.confidence)
            pitch = self._to_midi(note.pitch)
            pitch_closeness = 0.0
            if prev_pitch is not None and pitch is not None:
                pitch_closeness = -float(abs(pitch - prev_pitch))
            return (duration, confidence, pitch_closeness, -float(note.start_time))

        return max(group, key=ranking)

    def _remove_isolated_big_leaps(self, notes: List[Note]) -> tuple[list[Note], int]:
        if len(notes) <= 2:
            return notes, 0

        leap_limit = max(1, int(self.config.melody_large_jump_semitones))
        max_duration = max(0.0, float(self.config.melody_isolated_note_max_duration_sec))
        min_conf = max(0.0, min(1.0, float(self.config.melody_isolated_note_min_confidence)))

        kept: list[Note] = [notes[0]]
        removed = 0
        for idx in range(1, len(notes) - 1):
            prev_note = kept[-1]
            cur_note = notes[idx]
            next_note = notes[idx + 1]

            prev_midi = self._to_midi(prev_note.pitch)
            cur_midi = self._to_midi(cur_note.pitch)
            next_midi = self._to_midi(next_note.pitch)
            if prev_midi is None or cur_midi is None or next_midi is None:
                kept.append(cur_note)
                continue

            leap_prev = abs(cur_midi - prev_midi)
            leap_next = abs(next_midi - cur_midi)
            duration = max(0.0, float(cur_note.end_time) - float(cur_note.start_time))
            confidence = float(cur_note.confidence)
            is_isolated = (
                leap_prev >= leap_limit
                and leap_next >= leap_limit
                and (duration <= max_duration or confidence < min_conf)
            )
            if is_isolated:
                removed += 1
                continue
            kept.append(cur_note)

        kept.append(notes[-1])
        return kept, removed

    @staticmethod
    def _to_midi(pitch: str) -> int | None:
        try:
            return int(round(float(note_to_midi(str(pitch)))))
        except Exception:
            return None
