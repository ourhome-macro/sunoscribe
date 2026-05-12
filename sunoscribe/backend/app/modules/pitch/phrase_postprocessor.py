from __future__ import annotations

from dataclasses import dataclass, field
import math
from statistics import median
from typing import Any

from .note_utils import midi_to_note, note_to_midi
from .reason_codes import (
    OCTAVE_JUMP_CORRECTED,
    PHRASE_MEDIAN_SMOOTHED,
    SHORT_GAP_BRIDGED,
    SHORT_NOTE_ABSORBED,
)
from .types import Note


@dataclass(frozen=True)
class PhrasePostprocessConfig:
    enabled: bool = True
    max_phrase_gap_sec: float = 0.12
    short_gap_sec: float = 0.08
    same_pitch_tolerance_semitones: int = 1
    short_note_sec: float = 0.18
    short_note_neighbor_min_sec: float = 0.12
    octave_jump_semitones: int = 9
    octave_neighbor_tolerance_semitones: int = 2
    median_window: int = 5
    median_deviation_semitones: int = 2
    median_max_adjust_semitones: int = 4
    median_max_note_sec: float = 0.24
    min_confidence_for_mutation: float = 0.0
    vocal_min_midi: int = 48
    vocal_max_midi: int = 84
    max_iterations: int = 2


@dataclass
class PhrasePostprocessAction:
    action: str
    reason_code: str
    note_ids: list[str] = field(default_factory=list)
    output_note_id: str | None = None
    start_time_sec: float | None = None
    end_time_sec: float | None = None
    pitch_before_midi: float | None = None
    pitch_after_midi: float | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reason_code": self.reason_code,
            "note_ids": list(self.note_ids),
            "output_note_id": self.output_note_id,
            "start_time_sec": _round_optional(self.start_time_sec),
            "end_time_sec": _round_optional(self.end_time_sec),
            "pitch_before_midi": _round_optional(self.pitch_before_midi),
            "pitch_after_midi": _round_optional(self.pitch_after_midi),
            "details": dict(self.details),
        }


@dataclass
class PhrasePostprocessResult:
    notes: list[dict[str, Any]]
    actions: list[PhrasePostprocessAction] = field(default_factory=list)
    input_count: int = 0
    output_count: int = 0
    iteration_count: int = 0

    @property
    def action_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for action in self.actions:
            counts[action.action] = counts.get(action.action, 0) + 1
        return dict(sorted(counts.items()))

    @property
    def reason_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for action in self.actions:
            counts[action.reason_code] = counts.get(action.reason_code, 0) + 1
        return dict(sorted(counts.items()))

    def diagnostics(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "input_note_count": int(self.input_count),
            "output_note_count": int(self.output_count),
            "iteration_count": int(self.iteration_count),
            "action_count": len(self.actions),
            "action_counts": self.action_counts,
            "reason_code_counts": self.reason_counts,
            "actions": [action.to_dict() for action in self.actions],
        }


class PhraseAwarePostprocessor:
    def __init__(self, config: PhrasePostprocessConfig | None = None) -> None:
        self.config = config or PhrasePostprocessConfig()

    def process_dict_notes(self, notes: list[dict[str, Any]]) -> PhrasePostprocessResult:
        normalized = [self._normalize_dict_note(note, index) for index, note in enumerate(notes, start=1)]
        normalized = [note for note in normalized if note is not None]
        result = self._process(normalized)
        return result

    def process_notes(self, notes: list[Note]) -> tuple[list[Note], PhrasePostprocessResult]:
        dict_notes = [self._note_to_dict(note, index) for index, note in enumerate(notes, start=1)]
        result = self._process(dict_notes)
        processed_notes = [self._dict_to_note(note) for note in result.notes]
        return processed_notes, result

    def _process(self, input_notes: list[dict[str, Any]]) -> PhrasePostprocessResult:
        notes = sorted((self._clone_note(note) for note in input_notes), key=_note_sort_key)
        actions: list[PhrasePostprocessAction] = []
        if not self.config.enabled or len(notes) <= 1:
            return PhrasePostprocessResult(
                notes=notes,
                actions=[],
                input_count=len(input_notes),
                output_count=len(notes),
                iteration_count=0,
            )

        max_iterations = max(1, int(self.config.max_iterations))
        iteration_count = 0
        for _ in range(max_iterations):
            iteration_count += 1
            before = self._signature(notes)
            notes = self._bridge_short_gaps(notes, actions)
            notes = self._correct_octave_jumps(notes, actions)
            notes = self._correct_octave_islands(notes, actions)
            notes = self._median_smooth(notes, actions)
            notes = self._absorb_short_notes(notes, actions)
            notes = self._bridge_short_gaps(notes, actions)
            after = self._signature(notes)
            if after == before:
                break

        self._renumber_generated_ids(notes)
        return PhrasePostprocessResult(
            notes=notes,
            actions=actions,
            input_count=len(input_notes),
            output_count=len(notes),
            iteration_count=iteration_count,
        )

    def _bridge_short_gaps(
        self,
        notes: list[dict[str, Any]],
        actions: list[PhrasePostprocessAction],
    ) -> list[dict[str, Any]]:
        if len(notes) <= 1:
            return notes
        max_gap = max(0.0, float(self.config.short_gap_sec))
        tolerance = max(0, int(self.config.same_pitch_tolerance_semitones))
        bridged: list[dict[str, Any]] = []
        current = self._clone_note(notes[0])
        for nxt in notes[1:]:
            nxt = self._clone_note(nxt)
            gap = float(nxt["start_time_sec"]) - float(current["end_time_sec"])
            cur_midi = _pitch_midi(current)
            nxt_midi = _pitch_midi(nxt)
            can_bridge = (
                cur_midi is not None
                and nxt_midi is not None
                and gap > 0.0
                and gap <= max_gap
                and self._can_mutate(current)
                and self._can_mutate(nxt)
            )
            if can_bridge and abs(cur_midi - nxt_midi) <= tolerance:
                merged = self._merge_note_group(
                    [current, nxt],
                    pitch_midi=_weighted_pitch([current, nxt]) if tolerance > 0 else cur_midi,
                    reason_code=SHORT_GAP_BRIDGED,
                )
                actions.append(
                    PhrasePostprocessAction(
                        action="short_gap_bridge",
                        reason_code=SHORT_GAP_BRIDGED,
                        note_ids=_source_ids([current, nxt]),
                        output_note_id=str(merged.get("candidate_id")),
                        start_time_sec=float(current["start_time_sec"]),
                        end_time_sec=float(nxt["end_time_sec"]),
                        pitch_before_midi=cur_midi,
                        pitch_after_midi=_pitch_midi(merged),
                        details={"gap_sec": round(gap, 6), "mode": "merge"},
                    )
                )
                current = merged
                continue
            bridged.append(current)
            current = nxt
        bridged.append(current)
        return bridged

    def _absorb_short_notes(
        self,
        notes: list[dict[str, Any]],
        actions: list[PhrasePostprocessAction],
    ) -> list[dict[str, Any]]:
        if len(notes) <= 2:
            return notes
        resolved: list[dict[str, Any]] = [self._clone_note(notes[0])]
        idx = 1
        short_limit = max(0.0, float(self.config.short_note_sec))
        neighbor_min = max(0.0, float(self.config.short_note_neighbor_min_sec))
        max_gap = max(0.0, float(self.config.max_phrase_gap_sec))
        tolerance = max(0, int(self.config.same_pitch_tolerance_semitones))
        while idx < len(notes) - 1:
            prev_note = resolved[-1]
            cur_note = notes[idx]
            next_note = notes[idx + 1]
            prev_midi = _pitch_midi(prev_note)
            cur_midi = _pitch_midi(cur_note)
            next_midi = _pitch_midi(next_note)
            cur_duration = _duration(cur_note)
            prev_duration = _duration(prev_note)
            next_duration = _duration(next_note)
            same_neighbor_pitch = prev_midi is not None and next_midi is not None and abs(prev_midi - next_midi) <= tolerance
            local_phrase = self._is_local_phrase(prev_note, cur_note, next_note, max_gap=max_gap)
            short_enough = cur_duration <= short_limit and prev_duration >= neighbor_min and next_duration >= neighbor_min
            shorter_than_neighbors = cur_duration <= 0.75 * min(prev_duration, next_duration)
            prev_confidence = float(prev_note.get("confidence") or 0.0)
            cur_confidence = float(cur_note.get("confidence") or 0.0)
            next_confidence = float(next_note.get("confidence") or 0.0)
            not_stronger_than_neighbors = cur_confidence <= max(prev_confidence, next_confidence) + 0.05
            pitch_outlier = False
            if prev_midi is not None and cur_midi is not None and next_midi is not None:
                anchor = _median_int([prev_midi, next_midi])
                pitch_outlier = abs(cur_midi - anchor) >= max(1, tolerance + 1)
            absorbable = shorter_than_neighbors and (pitch_outlier or cur_confidence <= min(prev_confidence, next_confidence) + 0.05)
            if local_phrase and short_enough and same_neighbor_pitch and not_stronger_than_neighbors and absorbable:
                anchor_midi = _weighted_pitch([prev_note, next_note])
                merged = self._merge_note_group(
                    [prev_note, cur_note, next_note],
                    pitch_midi=anchor_midi,
                    reason_code=SHORT_NOTE_ABSORBED,
                )
                actions.append(
                    PhrasePostprocessAction(
                        action="short_note_absorb",
                        reason_code=SHORT_NOTE_ABSORBED,
                        note_ids=_source_ids([prev_note, cur_note, next_note]),
                        output_note_id=str(merged.get("candidate_id")),
                        start_time_sec=float(prev_note["start_time_sec"]),
                        end_time_sec=float(next_note["end_time_sec"]),
                        pitch_before_midi=cur_midi,
                        pitch_after_midi=_pitch_midi(merged),
                        details={"absorbed_duration_sec": round(cur_duration, 6)},
                    )
                )
                resolved[-1] = merged
                idx += 2
                continue
            resolved.append(self._clone_note(cur_note))
            idx += 1
        if idx == len(notes) - 1:
            resolved.append(self._clone_note(notes[-1]))
        return resolved

    def _correct_octave_jumps(
        self,
        notes: list[dict[str, Any]],
        actions: list[PhrasePostprocessAction],
    ) -> list[dict[str, Any]]:
        if len(notes) <= 2:
            return notes
        repaired = [self._clone_note(note) for note in notes]
        max_gap = max(0.0, float(self.config.max_phrase_gap_sec))
        jump_limit = max(7, int(self.config.octave_jump_semitones))
        neighbor_tolerance = max(0, int(self.config.octave_neighbor_tolerance_semitones))
        min_pitch = int(self.config.vocal_min_midi)
        max_pitch = int(self.config.vocal_max_midi)
        max_mutation_duration = max(
            float(self.config.short_note_sec),
            float(self.config.median_max_note_sec),
            0.35,
        )
        for idx in range(1, len(repaired) - 1):
            cur_note = repaired[idx]
            cur_midi = _pitch_midi(cur_note)
            if cur_midi is None or not self._can_mutate(cur_note):
                continue
            anchors = self._local_anchor_notes(repaired, idx, max_gap=max_gap, max_neighbors=2)
            if len(anchors) < 2:
                continue
            anchor_pitches = [_pitch_midi(note) for note, _ in anchors]
            anchor_pitches = [pitch for pitch in anchor_pitches if pitch is not None]
            if len(anchor_pitches) < 2:
                continue
            direct_neighbors = [repaired[idx - 1], repaired[idx + 1]]
            direct_pitches = [_pitch_midi(note) for note in direct_neighbors]
            direct_pitches = [pitch for pitch in direct_pitches if pitch is not None]
            if not direct_pitches:
                continue
            current_max_jump = max(abs(cur_midi - pitch) for pitch in direct_pitches)
            if current_max_jump < jump_limit:
                continue
            cur_duration = _duration(cur_note)
            cur_confidence = float(cur_note.get("confidence") or 0.0)
            strongest_anchor_confidence = max(float(note.get("confidence") or 0.0) for note, _ in anchors)
            if cur_duration > max_mutation_duration and cur_confidence >= strongest_anchor_confidence + 0.05:
                continue
            left_pitch = _pitch_midi(repaired[idx - 1])
            right_pitch = _pitch_midi(repaired[idx + 1])
            if (
                left_pitch is not None
                and right_pitch is not None
                and abs(left_pitch - right_pitch) > max(neighbor_tolerance, 3)
                and self._local_pitch_span(anchor_pitches) > 7
            ):
                continue
            current_score = self._octave_candidate_score(cur_midi, anchors, shift=0)
            current_anchor_max = max(abs(cur_midi - pitch) for pitch in anchor_pitches)
            best_pitch = cur_midi
            best_score = current_score
            best_anchor_max = current_anchor_max
            best_shift = 0
            for shift in (-24, -12, 12, 24):
                candidate = cur_midi + shift
                if candidate < min_pitch or candidate > max_pitch:
                    continue
                score = self._octave_candidate_score(candidate, anchors, shift=shift)
                anchor_max = max(abs(candidate - pitch) for pitch in anchor_pitches)
                ranking = (score, anchor_max, abs(shift))
                best_ranking = (best_score, best_anchor_max, abs(best_shift))
                if ranking < best_ranking:
                    best_pitch = candidate
                    best_score = score
                    best_anchor_max = anchor_max
                    best_shift = shift
            if best_shift == 0:
                continue
            strong_score_gain = best_score <= current_score * 0.55
            strong_jump_gain = best_anchor_max <= current_anchor_max - 5
            if not (strong_score_gain or strong_jump_gain):
                continue
            repaired[idx] = self._with_pitch(cur_note, best_pitch, OCTAVE_JUMP_CORRECTED)
            actions.append(
                PhrasePostprocessAction(
                    action="octave_jump_correction",
                    reason_code=OCTAVE_JUMP_CORRECTED,
                    note_ids=_source_ids([cur_note]),
                    output_note_id=str(repaired[idx].get("candidate_id")),
                    start_time_sec=float(cur_note["start_time_sec"]),
                    end_time_sec=float(cur_note["end_time_sec"]),
                    pitch_before_midi=cur_midi,
                    pitch_after_midi=best_pitch,
                    details={
                        "semitone_shift": int(round(best_shift)),
                        "anchor_count": len(anchors),
                        "score_before": round(current_score, 6),
                        "score_after": round(best_score, 6),
                    },
                )
            )
        return repaired

    def _correct_octave_islands(
        self,
        notes: list[dict[str, Any]],
        actions: list[PhrasePostprocessAction],
    ) -> list[dict[str, Any]]:
        if len(notes) < 3:
            return notes
        repaired = [self._clone_note(note) for note in notes]
        max_gap = max(0.0, float(self.config.max_phrase_gap_sec))
        jump_limit = max(7, int(self.config.octave_jump_semitones))
        min_pitch = int(self.config.vocal_min_midi)
        max_pitch = int(self.config.vocal_max_midi)
        max_island_notes = 2
        max_island_duration = max(0.35, float(self.config.median_max_note_sec) * 2.0)
        idx = 1
        while idx < len(repaired) - 1:
            best: tuple[int, int, list[float], float, float] | None = None
            for island_len in range(1, max_island_notes + 1):
                end_idx = idx + island_len
                if end_idx >= len(repaired):
                    continue
                prev_note = repaired[idx - 1]
                next_note = repaired[end_idx]
                island = repaired[idx:end_idx]
                if not self._phrase_window_is_local([prev_note] + island + [next_note], max_gap=max_gap):
                    continue
                if any(not self._can_mutate(note) for note in island):
                    continue
                island_start = float(island[0]["start_time_sec"])
                island_end = float(island[-1]["end_time_sec"])
                if island_end - island_start > max_island_duration:
                    continue
                prev_midi = _pitch_midi(prev_note)
                next_midi = _pitch_midi(next_note)
                island_pitches = [_pitch_midi(note) for note in island]
                if prev_midi is None or next_midi is None or any(pitch is None for pitch in island_pitches):
                    continue
                island_pitches = [float(pitch) for pitch in island_pitches if pitch is not None]
                raw_edge_max = max(abs(island_pitches[0] - prev_midi), abs(island_pitches[-1] - next_midi))
                if raw_edge_max < jump_limit:
                    continue
                if len(island_pitches) > 1 and max(island_pitches) - min(island_pitches) > 3:
                    continue
                current_score = abs(island_pitches[0] - prev_midi) + abs(island_pitches[-1] - next_midi)
                for shift in (-24, -12, 12, 24):
                    shifted = [pitch + shift for pitch in island_pitches]
                    if any(pitch < min_pitch or pitch > max_pitch for pitch in shifted):
                        continue
                    shifted_edge_max = max(abs(shifted[0] - prev_midi), abs(shifted[-1] - next_midi))
                    shifted_score = abs(shifted[0] - prev_midi) + abs(shifted[-1] - next_midi) + abs(shift) * 0.1
                    if shifted_edge_max >= raw_edge_max - 5 and shifted_score > current_score * 0.55:
                        continue
                    ranking = (shifted_score, shifted_edge_max, abs(shift))
                    if best is None or ranking < (best[3], best[4], abs(best[1])):
                        best = (island_len, shift, shifted, shifted_score, shifted_edge_max)
            if best is None:
                idx += 1
                continue
            island_len, shift, shifted_pitches, shifted_score, shifted_edge_max = best
            island = repaired[idx : idx + island_len]
            for offset, (note, shifted_pitch) in enumerate(zip(island, shifted_pitches)):
                repaired[idx + offset] = self._with_pitch(note, shifted_pitch, OCTAVE_JUMP_CORRECTED)
            actions.append(
                PhrasePostprocessAction(
                    action="octave_jump_correction",
                    reason_code=OCTAVE_JUMP_CORRECTED,
                    note_ids=_source_ids(island),
                    output_note_id=None,
                    start_time_sec=float(island[0]["start_time_sec"]),
                    end_time_sec=float(island[-1]["end_time_sec"]),
                    pitch_before_midi=_pitch_midi(island[0]),
                    pitch_after_midi=shifted_pitches[0],
                    details={
                        "mode": "short_octave_island",
                        "island_note_count": island_len,
                        "semitone_shift": int(round(shift)),
                        "score_after": round(shifted_score, 6),
                        "edge_max_after": round(shifted_edge_max, 6),
                    },
                )
            )
            idx += island_len
        return repaired

    def _median_smooth(
        self,
        notes: list[dict[str, Any]],
        actions: list[PhrasePostprocessAction],
    ) -> list[dict[str, Any]]:
        if len(notes) < 3:
            return notes
        window = max(3, int(self.config.median_window))
        if window % 2 == 0:
            window += 1
        half = window // 2
        deviation_limit = max(1, int(self.config.median_deviation_semitones))
        max_adjust = max(deviation_limit, int(self.config.median_max_adjust_semitones))
        max_duration = max(0.0, float(self.config.median_max_note_sec))
        max_gap = max(0.0, float(self.config.max_phrase_gap_sec))
        repaired = [self._clone_note(note) for note in notes]
        for idx, cur_note in enumerate(notes):
            cur_midi = _pitch_midi(cur_note)
            if cur_midi is None or not self._can_mutate(cur_note):
                continue
            if _duration(cur_note) > max_duration:
                continue
            left = max(0, idx - half)
            right = min(len(notes), idx + half + 1)
            window_notes = notes[left:right]
            if len(window_notes) < 3 or not self._phrase_window_is_local(window_notes, max_gap=max_gap):
                continue
            pitches = [_pitch_midi(note) for note in window_notes]
            pitches = [pitch for pitch in pitches if pitch is not None]
            if len(pitches) < 3:
                continue
            center = int(round(float(median(pitches))))
            deviation = abs(cur_midi - center)
            if deviation < deviation_limit or deviation > max_adjust:
                continue
            repaired[idx] = self._with_pitch(cur_note, center, PHRASE_MEDIAN_SMOOTHED)
            actions.append(
                PhrasePostprocessAction(
                    action="median_smoothing",
                    reason_code=PHRASE_MEDIAN_SMOOTHED,
                    note_ids=_source_ids([cur_note]),
                    output_note_id=str(repaired[idx].get("candidate_id")),
                    start_time_sec=float(cur_note["start_time_sec"]),
                    end_time_sec=float(cur_note["end_time_sec"]),
                    pitch_before_midi=cur_midi,
                    pitch_after_midi=center,
                    details={"window_note_count": len(window_notes), "deviation_semitones": int(round(deviation))},
                )
            )
        return repaired

    def _merge_note_group(
        self,
        notes: list[dict[str, Any]],
        *,
        pitch_midi: float | None,
        reason_code: str,
    ) -> dict[str, Any]:
        source_ids = _source_ids(notes)
        start = min(float(note["start_time_sec"]) for note in notes)
        end = max(float(note["end_time_sec"]) for note in notes)
        confidence = max(float(note.get("confidence") or 0.0) for note in notes)
        if pitch_midi is None:
            pitch_midi = _pitch_midi(notes[0]) or 60.0
        merged = self._clone_note(notes[0])
        merged["candidate_id"] = "+".join(source_ids) if source_ids else str(merged.get("candidate_id") or "merged")
        merged["start_time_sec"] = round(start, 6)
        merged["end_time_sec"] = round(end, 6)
        merged["duration_sec"] = round(max(0.0, end - start), 6)
        merged["pitch_center_midi"] = round(float(pitch_midi), 6)
        merged["confidence"] = round(confidence, 6)
        merged["source_contour_ids"] = _merged_list_values(notes, "source_contour_ids")
        merged["source_candidate_ids"] = source_ids
        merged["reason_codes"] = _unique([reason for note in notes for reason in list(note.get("reason_codes") or [])] + [reason_code])
        return merged

    def _with_pitch(self, note: dict[str, Any], pitch_midi: float, reason_code: str) -> dict[str, Any]:
        updated = self._clone_note(note)
        updated["pitch_center_midi"] = round(float(pitch_midi), 6)
        updated["reason_codes"] = _unique(list(updated.get("reason_codes") or []) + [reason_code])
        return updated

    def _can_mutate(self, note: dict[str, Any]) -> bool:
        confidence = float(note.get("confidence") or 0.0)
        return confidence >= max(0.0, float(self.config.min_confidence_for_mutation))

    def _is_local_phrase(
        self,
        prev_note: dict[str, Any],
        cur_note: dict[str, Any],
        next_note: dict[str, Any],
        *,
        max_gap: float,
    ) -> bool:
        gap_prev = float(cur_note["start_time_sec"]) - float(prev_note["end_time_sec"])
        gap_next = float(next_note["start_time_sec"]) - float(cur_note["end_time_sec"])
        return 0.0 <= gap_prev <= max_gap and 0.0 <= gap_next <= max_gap

    def _phrase_window_is_local(self, notes: list[dict[str, Any]], *, max_gap: float) -> bool:
        for left, right in zip(notes, notes[1:]):
            gap = float(right["start_time_sec"]) - float(left["end_time_sec"])
            if gap < 0.0 or gap > max_gap:
                return False
        return True

    def _local_anchor_notes(
        self,
        notes: list[dict[str, Any]],
        idx: int,
        *,
        max_gap: float,
        max_neighbors: int,
    ) -> list[tuple[dict[str, Any], float]]:
        anchors: list[tuple[dict[str, Any], float]] = []
        cur_note = notes[idx]
        cursor_end = float(cur_note["start_time_sec"])
        for left_idx in range(idx - 1, -1, -1):
            note = notes[left_idx]
            gap = cursor_end - float(note["end_time_sec"])
            if gap < 0.0 or gap > max_gap:
                break
            anchors.append((note, gap))
            cursor_end = float(note["start_time_sec"])
            if len([1 for anchor, _ in anchors if float(anchor["end_time_sec"]) <= float(cur_note["start_time_sec"])]) >= max_neighbors:
                break
        cursor_start = float(cur_note["end_time_sec"])
        right_count = 0
        for right_idx in range(idx + 1, len(notes)):
            note = notes[right_idx]
            gap = float(note["start_time_sec"]) - cursor_start
            if gap < 0.0 or gap > max_gap:
                break
            anchors.append((note, gap))
            cursor_start = float(note["end_time_sec"])
            right_count += 1
            if right_count >= max_neighbors:
                break
        return anchors

    def _octave_candidate_score(self, pitch_midi: float, anchors: list[tuple[dict[str, Any], float]], *, shift: int) -> float:
        max_gap = max(1e-6, float(self.config.max_phrase_gap_sec))
        score = abs(float(shift)) * 0.12
        for note, gap in anchors:
            anchor_pitch = _pitch_midi(note)
            if anchor_pitch is None:
                continue
            duration = max(0.03, _duration(note))
            confidence = max(0.05, float(note.get("confidence") or 0.0))
            time_weight = math.exp(-max(0.0, float(gap)) / max_gap)
            score += abs(float(pitch_midi) - anchor_pitch) * duration * confidence * time_weight
        return score

    @staticmethod
    def _local_pitch_span(pitches: list[float]) -> float:
        if not pitches:
            return 0.0
        return max(pitches) - min(pitches)


    def _normalize_dict_note(self, raw: dict[str, Any], index: int) -> dict[str, Any] | None:
        if not isinstance(raw, dict):
            return None
        start = _safe_float(_first(raw, "start_time_sec", "start_time", "onset_sec"))
        if start is None:
            start = 0.0
        end = _safe_float(_first(raw, "end_time_sec", "end_time", "offset_sec"))
        duration = _safe_float(_first(raw, "duration_sec", "duration"))
        if end is None and duration is not None:
            end = start + duration
        if end is None:
            end = start
        if end < start:
            end = start
        pitch = _safe_float(_first(raw, "pitch_center_midi", "midi_float", "pitch_midi", "midi_pitch"))
        if pitch is None:
            pitch_name = raw.get("pitch") or raw.get("pitch_name")
            if isinstance(pitch_name, str) and pitch_name.strip():
                try:
                    pitch = float(note_to_midi(pitch_name))
                except Exception:
                    pitch = None
        if pitch is None:
            return None
        confidence = _safe_float(raw.get("confidence"))
        if confidence is None:
            confidence = _safe_float(raw.get("mean_confidence")) or 0.0
        candidate_id = str(raw.get("candidate_id") or raw.get("id") or f"cand_{index:05d}")
        note = dict(raw)
        note["candidate_id"] = candidate_id
        note["start_time_sec"] = round(float(start), 6)
        note["end_time_sec"] = round(float(end), 6)
        note["duration_sec"] = round(max(0.0, float(end) - float(start)), 6)
        note["pitch_center_midi"] = round(float(pitch), 6)
        note["confidence"] = round(float(confidence), 6)
        note["source_contour_ids"] = list(raw.get("source_contour_ids") or raw.get("source_contours") or [])
        note["reason_codes"] = _unique([str(value) for value in raw.get("reason_codes") or [] if str(value).strip()])
        return note

    def _note_to_dict(self, note: Note, index: int) -> dict[str, Any]:
        return {
            "candidate_id": str(getattr(note, "candidate_id", None) or getattr(note, "id", None) or f"note_{index:05d}"),
            "start_time_sec": round(float(note.start_time), 6),
            "end_time_sec": round(float(note.end_time), 6),
            "duration_sec": round(max(0.0, float(note.end_time) - float(note.start_time)), 6),
            "pitch_center_midi": float(note_to_midi(str(note.pitch))),
            "confidence": round(float(note.confidence), 6),
            "reason_codes": list(getattr(note, "reason_codes", []) or []),
        }

    def _dict_to_note(self, note: dict[str, Any]) -> Note:
        pitch_midi = _pitch_midi(note)
        reason_codes = list(note.get("reason_codes") or [])
        return Note(
            pitch=midi_to_note(pitch_midi if pitch_midi is not None else 60.0),
            start_time=float(note["start_time_sec"]),
            end_time=float(note["end_time_sec"]),
            confidence=float(note.get("confidence") or 0.0),
            reason_codes=reason_codes,
        )

    def _clone_note(self, note: dict[str, Any]) -> dict[str, Any]:
        cloned = dict(note)
        cloned["source_contour_ids"] = list(note.get("source_contour_ids") or [])
        cloned["source_candidate_ids"] = list(note.get("source_candidate_ids") or [])
        cloned["reason_codes"] = list(note.get("reason_codes") or [])
        return cloned

    @staticmethod
    def _signature(notes: list[dict[str, Any]]) -> tuple[tuple[float, float, float | None], ...]:
        return tuple(
            (
                round(float(note.get("start_time_sec") or 0.0), 6),
                round(float(note.get("end_time_sec") or 0.0), 6),
                _round_optional(_pitch_midi(note)),
            )
            for note in notes
        )

    def _renumber_generated_ids(self, notes: list[dict[str, Any]]) -> None:
        for index, note in enumerate(notes, start=1):
            if not str(note.get("candidate_id") or "").strip():
                note["candidate_id"] = f"post_{index:05d}"


def _note_sort_key(note: dict[str, Any]) -> tuple[float, float, str]:
    return (float(note.get("start_time_sec") or 0.0), float(note.get("end_time_sec") or 0.0), str(note.get("candidate_id") or ""))


def _source_ids(notes: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for note in notes:
        raw_ids = list(note.get("source_candidate_ids") or [])
        if not raw_ids:
            raw_ids = [str(note.get("candidate_id") or "").strip()]
        for raw_id in raw_ids:
            raw_id = str(raw_id or "").strip()
            if raw_id and raw_id not in ids:
                ids.append(raw_id)
    return ids


def _merged_list_values(notes: list[dict[str, Any]], key: str) -> list[Any]:
    values: list[Any] = []
    for note in notes:
        for value in note.get(key) or []:
            if value not in values:
                values.append(value)
    return values


def _pitch_midi(note: dict[str, Any]) -> float | None:
    value = _safe_float(note.get("pitch_center_midi"))
    if value is not None:
        return value
    pitch = note.get("pitch") or note.get("pitch_name")
    if isinstance(pitch, str) and pitch.strip():
        try:
            return float(note_to_midi(pitch))
        except Exception:
            return None
    return None


def _weighted_pitch(notes: list[dict[str, Any]]) -> float | None:
    weighted_sum = 0.0
    weight_total = 0.0
    for note in notes:
        pitch = _pitch_midi(note)
        if pitch is None:
            continue
        duration = max(0.001, _duration(note))
        confidence = max(0.001, float(note.get("confidence") or 0.0))
        weight = duration * confidence
        weighted_sum += pitch * weight
        weight_total += weight
    if weight_total <= 0.0:
        return None
    return round(weighted_sum / weight_total)


def _median_int(values: list[float]) -> int:
    return int(round(float(median(values))))


def _duration(note: dict[str, Any]) -> float:
    duration = _safe_float(note.get("duration_sec"))
    if duration is not None:
        return max(0.0, duration)
    start = _safe_float(note.get("start_time_sec")) or 0.0
    end = _safe_float(note.get("end_time_sec")) or start
    return max(0.0, end - start)


def _first(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload:
            return payload.get(key)
    return None


def _safe_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def _round_optional(value: float | None) -> float | None:
    return round(float(value), 6) if value is not None else None


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result
