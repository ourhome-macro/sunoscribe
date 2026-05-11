from __future__ import annotations

from dataclasses import dataclass
from typing import List

from .config import PitchDetectionConfig
from .note_utils import midi_to_note, note_to_midi
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
            short_for_repair = False
            if pitch_midi is None:
                removed_pitch_range += 1
                continue
            if pitch_midi < int(self.config.melody_pitch_min_midi) or pitch_midi > int(self.config.melody_pitch_max_midi):
                removed_pitch_range += 1
                continue
            if duration < float(self.config.melody_min_duration_sec):
                removed_short += 1
                if confidence < float(self.config.melody_short_note_min_confidence):
                    continue
                short_for_repair = True
            if confidence < float(self.config.melody_min_confidence):
                removed_low_confidence += 1
                continue
            if (
                not short_for_repair
                and duration < float(self.config.melody_short_note_sec)
                and confidence < float(
                self.config.melody_short_note_min_confidence
                )
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
        repaired_notes = self._repair_phrase_notes(merged_notes)
        resolved_notes, removed_conflict = self._resolve_conflicts(repaired_notes)
        cleaned_notes, removed_big_leap = self._remove_isolated_big_leaps(resolved_notes)
        final_notes, merged_count_b = self._merge_adjacent(cleaned_notes)
        final_notes = self._drop_remaining_short_notes(final_notes)

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

    def _repair_phrase_notes(self, notes: List[Note]) -> list[Note]:
        if len(notes) <= 2:
            return notes

        repaired = self._correct_octave_outliers(notes)
        repaired = self._smooth_phrase_outliers(repaired)
        repaired = self._absorb_short_outliers(repaired)
        return repaired

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

    def _correct_octave_outliers(self, notes: List[Note]) -> list[Note]:
        if len(notes) <= 2:
            return notes

        repaired = [self._clone_note(note) for note in notes]
        max_gap = max(0.0, float(self.config.melody_merge_gap_sec))
        suspicious_jump = max(8, int(self.config.melody_large_jump_semitones) - 2)
        neighbor_window = max(1, int(self.config.melody_merge_pitch_tolerance_semitones))
        short_limit = max(
            float(self.config.melody_short_note_sec),
            float(self.config.melody_isolated_note_max_duration_sec),
        )
        min_conf = max(0.0, min(1.0, float(self.config.melody_isolated_note_min_confidence)))
        min_pitch = int(self.config.melody_pitch_min_midi)
        max_pitch = int(self.config.melody_pitch_max_midi)

        for idx in range(1, len(repaired) - 1):
            prev_note = repaired[idx - 1]
            cur_note = repaired[idx]
            next_note = repaired[idx + 1]
            if not self._is_local_phrase(prev_note, cur_note, next_note, max_gap=max_gap):
                continue

            prev_midi = self._to_midi(prev_note.pitch)
            cur_midi = self._to_midi(cur_note.pitch)
            next_midi = self._to_midi(next_note.pitch)
            if prev_midi is None or cur_midi is None or next_midi is None:
                continue
            if abs(prev_midi - next_midi) > neighbor_window:
                continue

            cur_duration = self._duration_sec(cur_note)
            cur_confidence = float(cur_note.confidence)
            jump_prev = abs(cur_midi - prev_midi)
            jump_next = abs(cur_midi - next_midi)
            if jump_prev < suspicious_jump and jump_next < suspicious_jump:
                continue
            if cur_duration > short_limit and cur_confidence >= min_conf:
                continue

            current_total = jump_prev + jump_next
            current_max = max(jump_prev, jump_next)
            best_candidate = cur_midi
            best_total = current_total
            best_max = current_max
            best_shift = 0

            for shift in (-24, -12, 12, 24):
                candidate = cur_midi + shift
                if candidate < min_pitch or candidate > max_pitch:
                    continue
                total_jump = abs(candidate - prev_midi) + abs(candidate - next_midi)
                max_jump = max(abs(candidate - prev_midi), abs(candidate - next_midi))
                ranking = (total_jump, max_jump, abs(shift))
                best_ranking = (best_total, best_max, abs(best_shift))
                if ranking < best_ranking:
                    best_candidate = candidate
                    best_total = total_jump
                    best_max = max_jump
                    best_shift = shift

            if best_candidate == cur_midi:
                continue
            if best_total + max(2, neighbor_window) > current_total:
                continue
            if best_max >= current_max:
                continue

            repaired[idx] = Note(
                pitch=midi_to_note(best_candidate),
                start_time=float(cur_note.start_time),
                end_time=float(cur_note.end_time),
                confidence=cur_confidence,
            )

        return repaired

    def _drop_remaining_short_notes(self, notes: List[Note]) -> list[Note]:
        min_duration = float(self.config.melody_min_duration_sec)
        return [note for note in notes if self._duration_sec(note) >= min_duration]

    def _smooth_phrase_outliers(self, notes: List[Note]) -> list[Note]:
        if len(notes) <= 2:
            return notes

        repaired = [self._clone_note(note) for note in notes]
        max_gap = max(0.0, float(self.config.melody_merge_gap_sec))
        neighbor_tolerance = max(1, int(self.config.melody_merge_pitch_tolerance_semitones))
        max_duration = max(
            float(self.config.melody_short_note_sec),
            float(self.config.melody_isolated_note_max_duration_sec),
        )
        min_conf = max(0.0, min(1.0, float(self.config.melody_isolated_note_min_confidence)))

        for idx in range(1, len(repaired) - 1):
            prev_note = repaired[idx - 1]
            cur_note = repaired[idx]
            next_note = repaired[idx + 1]
            if not self._is_local_phrase(prev_note, cur_note, next_note, max_gap=max_gap):
                continue

            prev_midi = self._to_midi(prev_note.pitch)
            cur_midi = self._to_midi(cur_note.pitch)
            next_midi = self._to_midi(next_note.pitch)
            if prev_midi is None or cur_midi is None or next_midi is None:
                continue
            if abs(prev_midi - next_midi) > neighbor_tolerance:
                continue

            cur_duration = self._duration_sec(cur_note)
            cur_confidence = float(cur_note.confidence)
            if cur_duration > max_duration and cur_confidence >= min_conf:
                continue

            anchor_midi = self._preferred_neighbor_midi(prev_note, next_note)
            if anchor_midi is None:
                continue

            deviation = abs(cur_midi - anchor_midi)
            stronger_neighbor_conf = max(float(prev_note.confidence), float(next_note.confidence))
            shorter_than_neighbors = cur_duration < min(self._duration_sec(prev_note), self._duration_sec(next_note))
            if deviation < 2 or deviation > 4:
                continue
            if cur_confidence >= stronger_neighbor_conf and not shorter_than_neighbors:
                continue

            repaired[idx] = Note(
                pitch=midi_to_note(anchor_midi),
                start_time=float(cur_note.start_time),
                end_time=float(cur_note.end_time),
                confidence=cur_confidence,
            )

        return repaired

    def _absorb_short_outliers(self, notes: List[Note]) -> list[Note]:
        if len(notes) <= 2:
            return notes

        max_gap = max(0.0, float(self.config.melody_merge_gap_sec))
        bridge_tolerance = max(1, int(self.config.melody_merge_pitch_tolerance_semitones))
        short_limit = max(float(self.config.melody_min_duration_sec), float(self.config.melody_short_note_sec))

        resolved: list[Note] = [self._clone_note(notes[0])]
        idx = 1
        while idx < len(notes) - 1:
            prev_note = resolved[-1]
            cur_note = notes[idx]
            next_note = notes[idx + 1]

            prev_midi = self._to_midi(prev_note.pitch)
            next_midi = self._to_midi(next_note.pitch)
            cur_duration = self._duration_sec(cur_note)
            prev_duration = self._duration_sec(prev_note)
            next_duration = self._duration_sec(next_note)
            cur_confidence = float(cur_note.confidence)
            stronger_neighbor_conf = min(float(prev_note.confidence), float(next_note.confidence))

            should_bridge = (
                prev_midi is not None
                and next_midi is not None
                and self._is_local_phrase(prev_note, cur_note, next_note, max_gap=max_gap)
                and abs(prev_midi - next_midi) <= bridge_tolerance
                and cur_duration <= short_limit
                and cur_duration <= min(prev_duration, next_duration)
                and (
                    cur_confidence <= stronger_neighbor_conf + 0.05
                    or cur_duration <= 0.75 * min(prev_duration, next_duration)
                )
            )
            if should_bridge:
                anchor_midi = self._preferred_neighbor_midi(prev_note, next_note)
                anchor_pitch = midi_to_note(anchor_midi) if anchor_midi is not None else prev_note.pitch
                resolved[-1] = Note(
                    pitch=anchor_pitch,
                    start_time=float(prev_note.start_time),
                    end_time=max(float(prev_note.end_time), float(next_note.end_time)),
                    confidence=max(float(prev_note.confidence), cur_confidence, float(next_note.confidence)),
                )
                idx += 2
                continue

            resolved.append(self._clone_note(cur_note))
            idx += 1

        if idx == len(notes) - 1:
            resolved.append(self._clone_note(notes[-1]))

        return resolved

    @staticmethod
    def _clone_note(note: Note) -> Note:
        return Note(
            pitch=str(note.pitch),
            start_time=float(note.start_time),
            end_time=float(note.end_time),
            confidence=float(note.confidence),
        )

    @staticmethod
    def _duration_sec(note: Note) -> float:
        return max(0.0, float(note.end_time) - float(note.start_time))

    @staticmethod
    def _is_local_phrase(prev_note: Note, cur_note: Note, next_note: Note, *, max_gap: float) -> bool:
        gap_prev = float(cur_note.start_time) - float(prev_note.end_time)
        gap_next = float(next_note.start_time) - float(cur_note.end_time)
        return gap_prev >= 0.0 and gap_prev <= max_gap and gap_next >= 0.0 and gap_next <= max_gap

    def _preferred_neighbor_midi(self, prev_note: Note, next_note: Note) -> int | None:
        prev_midi = self._to_midi(prev_note.pitch)
        next_midi = self._to_midi(next_note.pitch)
        if prev_midi is None or next_midi is None:
            return prev_midi if prev_midi is not None else next_midi
        if prev_midi == next_midi:
            return prev_midi

        prev_duration = self._duration_sec(prev_note)
        next_duration = self._duration_sec(next_note)
        prev_score = (float(prev_note.confidence), prev_duration)
        next_score = (float(next_note.confidence), next_duration)
        return prev_midi if prev_score >= next_score else next_midi

    @staticmethod
    def _to_midi(pitch: str) -> int | None:
        try:
            return int(round(float(note_to_midi(str(pitch)))))
        except Exception:
            return None
