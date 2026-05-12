from __future__ import annotations

from dataclasses import dataclass, field
import math
from statistics import mean
from typing import Any

from .melody_selection_artifact import selected_notes_to_pitch_notes
from .note_utils import midi_to_note, note_to_midi
from .reason_codes import (
    DP_FALLBACK,
    DP_NO_CANDIDATE_PATH,
    FRAGMENTATION_RISK,
    HIGH_QUANTIZE_ERROR,
    OVERMERGE_RISK,
    QUANTIZER_BACKEND_UNSUPPORTED,
    RHYTHM_GRID_UNAVAILABLE,
    TOO_SHORT,
    UNCERTAIN,
)


@dataclass(frozen=True)
class QuantizerArtifactConfig:
    backend: str = "dp_v1"
    allow_required_fallback: bool = False
    ppqn: int = 480
    grid_division: int = 16
    allowed_durations_beats: list[float] = field(default_factory=lambda: [0.25, 0.5, 1.0, 2.0, 4.0])
    high_error_sec: float = 0.12
    min_duration_beats: float = 0.25
    dp_search_radius_steps: int = 2
    dp_onset_error_weight: float = 1.0
    dp_duration_error_weight: float = 0.45
    dp_overlap_penalty: float = 8.0
    dp_backtrack_penalty: float = 3.0
    fragmentation_gap_beats: float = 0.25
    fragmentation_pitch_tolerance: int = 1
    overmerge_overlap_beats: float = 0.125
    overmerge_duration_extension_beats: float = 0.25


@dataclass(frozen=True)
class _BeatGrid:
    tempo_bpm: float
    beat_duration_sec: float
    beat_times: tuple[float, ...]

    def time_to_beat(self, time_sec: float) -> float:
        time_sec = float(time_sec)
        if len(self.beat_times) >= 2:
            beats = self.beat_times
            if time_sec <= beats[0]:
                first_interval = max(1e-6, beats[1] - beats[0])
                return (time_sec - beats[0]) / first_interval
            for index in range(len(beats) - 1):
                left = beats[index]
                right = beats[index + 1]
                if left <= time_sec <= right:
                    interval = max(1e-6, right - left)
                    return float(index) + ((time_sec - left) / interval)
            last_interval = max(1e-6, beats[-1] - beats[-2])
            return float(len(beats) - 1) + ((time_sec - beats[-1]) / last_interval)
        anchor = self.beat_times[0] if self.beat_times else 0.0
        return (time_sec - anchor) / max(1e-6, self.beat_duration_sec)

    def beat_to_time(self, beat: float) -> float:
        beat = float(beat)
        if len(self.beat_times) >= 2:
            beats = self.beat_times
            if beat <= 0.0:
                first_interval = max(1e-6, beats[1] - beats[0])
                return beats[0] + beat * first_interval
            left_index = int(math.floor(beat))
            fraction = beat - left_index
            if left_index < len(beats) - 1:
                return beats[left_index] + fraction * max(1e-6, beats[left_index + 1] - beats[left_index])
            last_interval = max(1e-6, beats[-1] - beats[-2])
            return beats[-1] + (beat - (len(beats) - 1)) * last_interval
        anchor = self.beat_times[0] if self.beat_times else 0.0
        return anchor + beat * max(1e-6, self.beat_duration_sec)


@dataclass(frozen=True)
class _RawNote:
    source_note: dict[str, Any]
    index: int
    source_candidate_id: str
    start_time_sec: float
    end_time_sec: float
    duration_sec: float
    start_beat_raw: float
    duration_beats_raw: float
    pitch_midi: int
    pitch_midi_float: float | None
    confidence: float


@dataclass(frozen=True)
class _QuantizeCandidate:
    note: _RawNote
    start_beat: float
    duration_beats: float
    quantized_start_time_sec: float
    quantized_end_time_sec: float
    onset_error_sec: float
    onset_error_beats: float
    duration_error_sec: float
    duration_error_beats: float
    local_cost: float


class QuantizedNotesArtifactBuilder:
    def __init__(self, config: QuantizerArtifactConfig | None = None) -> None:
        self.config = config or QuantizerArtifactConfig()

    def build(
        self,
        *,
        selected_melody: dict[str, Any] | None,
        rhythm_grid: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        selected_notes = selected_notes_to_pitch_notes(selected_melody)
        if not selected_notes:
            return None

        requested_backend = str(self.config.backend or "local_snap").strip().lower()
        tempo_bpm = _tempo_bpm(rhythm_grid)
        beat_grid = _beat_grid(rhythm_grid, tempo_bpm)
        fallback_used = False
        fallback_reason = None

        if requested_backend == "dp_v1" and beat_grid is not None:
            raw_notes = [self._raw_note(note, index, beat_grid) for index, note in enumerate(selected_notes, start=1)]
            candidates = [self._dp_candidates(raw_note, beat_grid) for raw_note in raw_notes]
            selected_candidates = self._select_dp_path(candidates) if all(candidates) else []
            if selected_candidates:
                actual_backend = "dp_v1"
                notes = [self._note_from_candidate(candidate) for candidate in selected_candidates]
            elif self.config.allow_required_fallback:
                fallback_used = True
                fallback_reason = DP_NO_CANDIDATE_PATH
                actual_backend = "local_snap"
                notes = self._build_local_snap_notes(selected_notes, beat_grid, fallback_reason=fallback_reason)
            else:
                raise ValueError("required quantizer backend dp_v1 failed: no candidate path")
        elif requested_backend == "dp_v1":
            if not self.config.allow_required_fallback:
                raise ValueError("required quantizer backend dp_v1 failed: rhythm grid unavailable")
            fallback_used = True
            fallback_reason = RHYTHM_GRID_UNAVAILABLE
            actual_backend = "local_snap"
            notes = self._build_local_snap_notes(selected_notes, beat_grid, fallback_reason=fallback_reason)
        elif requested_backend == "local_snap":
            actual_backend = "local_snap"
            notes = self._build_local_snap_notes(selected_notes, beat_grid, fallback_reason=None)
        else:
            fallback_used = True
            fallback_reason = QUANTIZER_BACKEND_UNSUPPORTED
            actual_backend = "local_snap"
            notes = self._build_local_snap_notes(selected_notes, beat_grid, fallback_reason=fallback_reason)

        diagnostics = self._diagnostics(notes=notes, selected_notes=selected_notes)
        notes = self._apply_diagnostic_reason_codes(notes, diagnostics)
        errors = [float(note.get("quantize_error_sec") or 0.0) for note in notes]
        summary = {
            "note_count": len(notes),
            "mean_quantize_error_sec": round(mean(errors), 6) if errors else 0.0,
            "p95_quantize_error_sec": _round_or_none(_percentile(errors, 0.95)) if errors else 0.0,
            "max_quantize_error_sec": round(max(errors), 6) if errors else 0.0,
            "uncertain_count": sum(1 for note in notes if note.get("uncertain")),
            "fallback_used": fallback_used,
            "fallback_reason": fallback_reason,
            "fragmentation": diagnostics["fragmentation"],
            "overmerge": diagnostics["overmerge"],
        }
        return {
            "version": "quantized_notes_v1",
            "quantizer_backend": actual_backend,
            "requested_quantizer_backend": requested_backend,
            "fallback_used": fallback_used,
            "fallback_reason": fallback_reason,
            "ppqn": int(self.config.ppqn),
            "tempo_bpm": tempo_bpm,
            "meter": _meter(rhythm_grid),
            "source_rhythm_grid": "rhythm_grid" if isinstance(rhythm_grid, dict) else None,
            "notes": notes,
            "summary": summary,
            "diagnostics": diagnostics,
            "config": {
                "backend": self.config.backend,
                "ppqn": self.config.ppqn,
                "grid_division": self.config.grid_division,
                "allowed_durations_beats": list(self.config.allowed_durations_beats),
                "dp_search_radius_steps": self.config.dp_search_radius_steps,
            },
        }

    def _build_local_snap_notes(
        self,
        selected_notes: list[dict[str, Any]],
        beat_grid: _BeatGrid | None,
        *,
        fallback_reason: str | None,
    ) -> list[dict[str, Any]]:
        return [
            self._quantize_note(note, index, beat_grid, fallback_reason=fallback_reason)
            for index, note in enumerate(selected_notes, start=1)
        ]

    def _quantize_note(
        self,
        note: dict[str, Any],
        index: int,
        beat_grid: _BeatGrid | None,
        *,
        fallback_reason: str | None,
    ) -> dict[str, Any]:
        start_time = _safe_float(note.get("start_time")) or 0.0
        end_time = _safe_float(note.get("end_time")) or start_time
        if end_time < start_time:
            end_time = start_time
        duration_sec = max(0.0, end_time - start_time)
        pitch_float = _pitch_float(note)
        pitch_midi = int(round(pitch_float)) if pitch_float is not None else 60
        confidence = _safe_float(note.get("confidence")) or 0.0
        if beat_grid is not None:
            start_beat_raw = beat_grid.time_to_beat(start_time)
            end_beat_raw = beat_grid.time_to_beat(end_time)
            duration_beat_raw = max(0.0, end_beat_raw - start_beat_raw)
            grid_beats = 4.0 / max(1, self.config.grid_division)
            start_beat = round(start_beat_raw / grid_beats) * grid_beats
            duration_beats = min(self.config.allowed_durations_beats, key=lambda value: abs(value - duration_beat_raw))
            quantized_start_time = beat_grid.beat_to_time(start_beat)
            quantized_end_time = beat_grid.beat_to_time(start_beat + duration_beats)
            quantize_error_sec = abs(quantized_start_time - start_time)
            start_tick = int(round(start_beat * self.config.ppqn))
            duration_tick = max(1, int(round(duration_beats * self.config.ppqn)))
            quantize_error_beats = abs(start_beat - start_beat_raw)
            measure_index = int(start_beat // 4) if start_beat >= 0 else None
            beat_in_measure = (start_beat % 4.0) + 1.0 if start_beat >= 0 else None
            duration_error_beats = abs(duration_beats - duration_beat_raw)
            duration_error_sec = abs((quantized_end_time - quantized_start_time) - duration_sec)
        else:
            start_beat = None
            duration_beats = None
            quantize_error_sec = 0.0
            start_tick = int(round(start_time * self.config.ppqn))
            duration_tick = max(1, int(round(duration_sec * self.config.ppqn)))
            quantize_error_beats = None
            measure_index = None
            beat_in_measure = None
            quantized_start_time = start_time
            quantized_end_time = end_time
            duration_error_beats = None
            duration_error_sec = 0.0

        reason_codes: list[str] = list(note.get("reason_codes") or [])
        if fallback_reason:
            reason_codes.extend([DP_FALLBACK, fallback_reason])
        if quantize_error_sec > self.config.high_error_sec:
            reason_codes.append(HIGH_QUANTIZE_ERROR)
        if duration_beats is not None and duration_beats < self.config.min_duration_beats:
            reason_codes.append(TOO_SHORT)
        uncertain = bool(reason_codes)
        if uncertain:
            reason_codes.append(UNCERTAIN)
        return {
            "id": f"qn_{index:05d}",
            "source_candidate_id": str(note.get("source_candidate_id") or note.get("id") or f"cand_{index:05d}"),
            "pitch_midi": pitch_midi,
            "pitch_midi_float": round(float(pitch_float), 6) if pitch_float is not None else None,
            "pitch": midi_to_note(pitch_midi),
            "start_time_sec": round(start_time, 6),
            "end_time_sec": round(end_time, 6),
            "quantized_start_time_sec": round(quantized_start_time, 6),
            "quantized_end_time_sec": round(quantized_end_time, 6),
            "quantized_duration_sec": round(max(0.0, quantized_end_time - quantized_start_time), 6),
            "start_beat": _round_or_none(start_beat),
            "duration_beats": _round_or_none(duration_beats),
            "start_tick": start_tick,
            "duration_tick": duration_tick,
            "measure_index": measure_index,
            "beat_in_measure": _round_or_none(beat_in_measure),
            "confidence": round(max(0.0, min(1.0, confidence)), 6),
            "quantize_error_sec": round(quantize_error_sec, 6),
            "quantize_error_beats": _round_or_none(quantize_error_beats),
            "duration_error_sec": round(duration_error_sec, 6),
            "duration_error_beats": _round_or_none(duration_error_beats),
            "uncertain": uncertain,
            "reason_codes": _unique(reason_codes),
        }

    def _raw_note(self, note: dict[str, Any], index: int, beat_grid: _BeatGrid) -> _RawNote:
        start_time = _safe_float(note.get("start_time")) or 0.0
        end_time = _safe_float(note.get("end_time")) or start_time
        if end_time < start_time:
            end_time = start_time
        pitch_float = _pitch_float(note)
        pitch_midi = int(round(pitch_float)) if pitch_float is not None else 60
        start_beat = beat_grid.time_to_beat(start_time)
        end_beat = beat_grid.time_to_beat(end_time)
        return _RawNote(
            source_note=note,
            index=index,
            source_candidate_id=str(note.get("source_candidate_id") or note.get("id") or f"cand_{index:05d}"),
            start_time_sec=start_time,
            end_time_sec=end_time,
            duration_sec=max(0.0, end_time - start_time),
            start_beat_raw=start_beat,
            duration_beats_raw=max(0.0, end_beat - start_beat),
            pitch_midi=pitch_midi,
            pitch_midi_float=pitch_float,
            confidence=max(0.0, min(1.0, _safe_float(note.get("confidence")) or 0.0)),
        )

    def _dp_candidates(self, raw_note: _RawNote, beat_grid: _BeatGrid) -> list[_QuantizeCandidate]:
        grid_beats = 4.0 / max(1, int(self.config.grid_division))
        radius = max(0, int(self.config.dp_search_radius_steps))
        center_step = int(round(raw_note.start_beat_raw / grid_beats))
        durations = sorted(
            {
                max(float(self.config.min_duration_beats), float(duration))
                for duration in self.config.allowed_durations_beats
                if _safe_float(duration) is not None and float(duration) > 0.0
            }
        )
        if not durations:
            return []
        candidates: list[_QuantizeCandidate] = []
        seen: set[tuple[int, int]] = set()
        for step_index in range(center_step - radius, center_step + radius + 1):
            start_beat = round(step_index * grid_beats, 9)
            if start_beat < 0.0:
                continue
            for duration_beats in durations:
                duration_step = int(round(duration_beats / grid_beats))
                key = (step_index, duration_step)
                if key in seen:
                    continue
                seen.add(key)
                quantized_start_time = beat_grid.beat_to_time(start_beat)
                quantized_end_time = beat_grid.beat_to_time(start_beat + duration_beats)
                onset_error_beats = abs(start_beat - raw_note.start_beat_raw)
                duration_error_beats = abs(duration_beats - raw_note.duration_beats_raw)
                onset_error_sec = abs(quantized_start_time - raw_note.start_time_sec)
                duration_error_sec = abs((quantized_end_time - quantized_start_time) - raw_note.duration_sec)
                local_cost = (
                    self.config.dp_onset_error_weight * (onset_error_beats**2)
                    + self.config.dp_duration_error_weight * (duration_error_beats**2)
                )
                candidates.append(
                    _QuantizeCandidate(
                        note=raw_note,
                        start_beat=start_beat,
                        duration_beats=duration_beats,
                        quantized_start_time_sec=quantized_start_time,
                        quantized_end_time_sec=quantized_end_time,
                        onset_error_sec=onset_error_sec,
                        onset_error_beats=onset_error_beats,
                        duration_error_sec=duration_error_sec,
                        duration_error_beats=duration_error_beats,
                        local_cost=local_cost,
                    )
                )
        return sorted(candidates, key=lambda item: (item.local_cost, item.start_beat, item.duration_beats))[:24]

    def _select_dp_path(self, candidates_by_note: list[list[_QuantizeCandidate]]) -> list[_QuantizeCandidate]:
        if not candidates_by_note:
            return []
        costs: list[dict[int, tuple[float, int | None]]] = []
        costs.append({index: (candidate.local_cost, None) for index, candidate in enumerate(candidates_by_note[0])})
        for note_index in range(1, len(candidates_by_note)):
            current_costs: dict[int, tuple[float, int | None]] = {}
            for current_index, current in enumerate(candidates_by_note[note_index]):
                best_cost: float | None = None
                best_previous: int | None = None
                for previous_index, previous in enumerate(candidates_by_note[note_index - 1]):
                    previous_state = costs[note_index - 1].get(previous_index)
                    if previous_state is None:
                        continue
                    total = previous_state[0] + current.local_cost + self._transition_cost(previous, current)
                    if best_cost is None or total < best_cost:
                        best_cost = total
                        best_previous = previous_index
                if best_cost is not None:
                    current_costs[current_index] = (best_cost, best_previous)
            if not current_costs:
                return []
            costs.append(current_costs)
        last_index = min(costs[-1], key=lambda idx: costs[-1][idx][0])
        path: list[_QuantizeCandidate] = []
        for note_index in range(len(candidates_by_note) - 1, -1, -1):
            path.append(candidates_by_note[note_index][last_index])
            previous_index = costs[note_index][last_index][1]
            if previous_index is None:
                break
            last_index = previous_index
        return list(reversed(path)) if len(path) == len(candidates_by_note) else []

    def _transition_cost(self, previous: _QuantizeCandidate, current: _QuantizeCandidate) -> float:
        previous_end = previous.start_beat + previous.duration_beats
        overlap = max(0.0, previous_end - current.start_beat)
        raw_gap = max(0.0, current.note.start_beat_raw - (previous.note.start_beat_raw + previous.note.duration_beats_raw))
        quantized_gap = current.start_beat - previous_end
        cost = overlap * self.config.dp_overlap_penalty
        if overlap > 0.0:
            cost += self.config.dp_overlap_penalty
        if raw_gap >= 0.0 and quantized_gap < 0.0:
            cost += abs(quantized_gap) * self.config.dp_backtrack_penalty
        return cost

    def _note_from_candidate(self, candidate: _QuantizeCandidate) -> dict[str, Any]:
        raw_note = candidate.note
        start_tick = int(round(candidate.start_beat * self.config.ppqn))
        duration_tick = max(1, int(round(candidate.duration_beats * self.config.ppqn)))
        measure_index = int(candidate.start_beat // 4) if candidate.start_beat >= 0 else None
        beat_in_measure = (candidate.start_beat % 4.0) + 1.0 if candidate.start_beat >= 0 else None
        reason_codes: list[str] = list(raw_note.source_note.get("reason_codes") or [])
        if candidate.onset_error_sec > self.config.high_error_sec:
            reason_codes.append(HIGH_QUANTIZE_ERROR)
        if candidate.duration_beats < self.config.min_duration_beats:
            reason_codes.append(TOO_SHORT)
        uncertain = bool(reason_codes)
        if uncertain:
            reason_codes.append(UNCERTAIN)
        return {
            "id": f"qn_{raw_note.index:05d}",
            "source_candidate_id": raw_note.source_candidate_id,
            "pitch_midi": raw_note.pitch_midi,
            "pitch_midi_float": round(float(raw_note.pitch_midi_float), 6) if raw_note.pitch_midi_float is not None else None,
            "pitch": midi_to_note(raw_note.pitch_midi),
            "start_time_sec": round(raw_note.start_time_sec, 6),
            "end_time_sec": round(raw_note.end_time_sec, 6),
            "quantized_start_time_sec": round(candidate.quantized_start_time_sec, 6),
            "quantized_end_time_sec": round(candidate.quantized_end_time_sec, 6),
            "quantized_duration_sec": round(max(0.0, candidate.quantized_end_time_sec - candidate.quantized_start_time_sec), 6),
            "start_beat": _round_or_none(candidate.start_beat),
            "duration_beats": _round_or_none(candidate.duration_beats),
            "start_tick": start_tick,
            "duration_tick": duration_tick,
            "measure_index": measure_index,
            "beat_in_measure": _round_or_none(beat_in_measure),
            "confidence": round(raw_note.confidence, 6),
            "quantize_error_sec": round(candidate.onset_error_sec, 6),
            "quantize_error_beats": _round_or_none(candidate.onset_error_beats),
            "duration_error_sec": round(candidate.duration_error_sec, 6),
            "duration_error_beats": _round_or_none(candidate.duration_error_beats),
            "uncertain": uncertain,
            "reason_codes": _unique(reason_codes),
        }

    def _diagnostics(self, *, notes: list[dict[str, Any]], selected_notes: list[dict[str, Any]]) -> dict[str, Any]:
        fragmentation = self._fragmentation_diagnostics(notes)
        overmerge = self._overmerge_diagnostics(notes)
        errors = [float(note.get("quantize_error_sec") or 0.0) for note in notes]
        duration_errors = [float(note.get("duration_error_beats") or 0.0) for note in notes]
        return {
            "input_selected_note_count": len(selected_notes),
            "output_note_count": len(notes),
            "error_stats": {
                "mean_quantize_error_sec": round(mean(errors), 6) if errors else 0.0,
                "p95_quantize_error_sec": _round_or_none(_percentile(errors, 0.95)) if errors else 0.0,
                "max_quantize_error_sec": round(max(errors), 6) if errors else 0.0,
                "mean_duration_error_beats": round(mean(duration_errors), 6) if duration_errors else 0.0,
                "max_duration_error_beats": round(max(duration_errors), 6) if duration_errors else 0.0,
            },
            "fragmentation": fragmentation,
            "overmerge": overmerge,
        }

    def _fragmentation_diagnostics(self, notes: list[dict[str, Any]]) -> dict[str, Any]:
        pairs: list[dict[str, Any]] = []
        max_gap = max(0.0, float(self.config.fragmentation_gap_beats))
        pitch_tolerance = max(0, int(self.config.fragmentation_pitch_tolerance))
        ordered = sorted(notes, key=lambda item: (_safe_float(item.get("start_beat")) or 0.0, item.get("id") or ""))
        for left, right in zip(ordered, ordered[1:]):
            left_start = _safe_float(left.get("start_beat"))
            left_duration = _safe_float(left.get("duration_beats"))
            right_start = _safe_float(right.get("start_beat"))
            if left_start is None or left_duration is None or right_start is None:
                continue
            gap = right_start - (left_start + left_duration)
            left_pitch = _safe_float(left.get("pitch_midi"))
            right_pitch = _safe_float(right.get("pitch_midi"))
            if gap < -1e-9 or gap > max_gap or left_pitch is None or right_pitch is None:
                continue
            if abs(left_pitch - right_pitch) <= pitch_tolerance:
                pairs.append({"left_id": left.get("id"), "right_id": right.get("id"), "gap_beats": round(gap, 6)})
        return {
            "possible_fragment_pair_count": len(pairs),
            "risk_score": _round_or_none(_safe_ratio(len(pairs), max(1, len(notes) - 1))) or 0.0,
            "pairs": pairs[:20],
        }

    def _overmerge_diagnostics(self, notes: list[dict[str, Any]]) -> dict[str, Any]:
        overlap_pairs: list[dict[str, Any]] = []
        extended_note_ids: list[str] = []
        min_overlap = max(0.0, float(self.config.overmerge_overlap_beats))
        min_extension = max(0.0, float(self.config.overmerge_duration_extension_beats))
        ordered = sorted(notes, key=lambda item: (_safe_float(item.get("start_beat")) or 0.0, item.get("id") or ""))
        for note in ordered:
            duration_error = _safe_float(note.get("duration_error_beats")) or 0.0
            raw_duration_sec = max(0.0, (_safe_float(note.get("end_time_sec")) or 0.0) - (_safe_float(note.get("start_time_sec")) or 0.0))
            quantized_duration_sec = _safe_float(note.get("quantized_duration_sec")) or raw_duration_sec
            if duration_error >= min_extension and quantized_duration_sec > raw_duration_sec:
                extended_note_ids.append(str(note.get("id")))
        for left, right in zip(ordered, ordered[1:]):
            left_start = _safe_float(left.get("start_beat"))
            left_duration = _safe_float(left.get("duration_beats"))
            right_start = _safe_float(right.get("start_beat"))
            if left_start is None or left_duration is None or right_start is None:
                continue
            overlap = (left_start + left_duration) - right_start
            if overlap >= min_overlap:
                overlap_pairs.append({"left_id": left.get("id"), "right_id": right.get("id"), "overlap_beats": round(overlap, 6)})
        risk_items = len(set(extended_note_ids)) + len(overlap_pairs)
        return {
            "possible_overmerge_note_count": len(set(extended_note_ids)),
            "overlap_pair_count": len(overlap_pairs),
            "risk_score": _round_or_none(_safe_ratio(risk_items, max(1, len(notes)))) or 0.0,
            "extended_note_ids": sorted(set(extended_note_ids))[:20],
            "overlap_pairs": overlap_pairs[:20],
        }

    def _apply_diagnostic_reason_codes(
        self,
        notes: list[dict[str, Any]],
        diagnostics: dict[str, Any],
    ) -> list[dict[str, Any]]:
        fragmentation = diagnostics.get("fragmentation") if isinstance(diagnostics.get("fragmentation"), dict) else {}
        overmerge = diagnostics.get("overmerge") if isinstance(diagnostics.get("overmerge"), dict) else {}
        fragmented_ids = {
            str(pair.get(key))
            for pair in fragmentation.get("pairs") or []
            if isinstance(pair, dict)
            for key in ("left_id", "right_id")
            if pair.get(key)
        }
        overmerged_ids = set(str(value) for value in overmerge.get("extended_note_ids") or [] if value)
        for pair in overmerge.get("overlap_pairs") or []:
            if isinstance(pair, dict):
                overmerged_ids.update(str(pair.get(key)) for key in ("left_id", "right_id") if pair.get(key))
        updated_notes: list[dict[str, Any]] = []
        for note in notes:
            updated = dict(note)
            reasons = list(updated.get("reason_codes") or [])
            if str(updated.get("id")) in fragmented_ids:
                reasons.append(FRAGMENTATION_RISK)
            if str(updated.get("id")) in overmerged_ids:
                reasons.append(OVERMERGE_RISK)
            reasons = _unique(reasons)
            if reasons and UNCERTAIN not in reasons:
                reasons.append(UNCERTAIN)
            updated["reason_codes"] = _unique(reasons)
            updated["uncertain"] = bool(updated["reason_codes"])
            updated_notes.append(updated)
        return updated_notes


def score_ir_note_annotations(quantized_notes: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(quantized_notes, dict):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for note in quantized_notes.get("notes") or []:
        if not isinstance(note, dict):
            continue
        source_id = str(note.get("source_candidate_id") or "")
        if source_id:
            result[source_id] = {
                "quantized_note_id": note.get("id"),
                "source_candidate_id": source_id,
                "uncertain": bool(note.get("uncertain")),
                "reason_codes": list(note.get("reason_codes") or []),
                "quantize_error_sec": note.get("quantize_error_sec"),
            }
    return result


def _beat_grid(rhythm_grid: dict[str, Any] | None, tempo_bpm: float | None) -> _BeatGrid | None:
    if tempo_bpm is None or tempo_bpm <= 0:
        return None
    beat_duration = 60.0 / tempo_bpm
    raw_beat_times = rhythm_grid.get("beat_times") if isinstance(rhythm_grid, dict) else None
    beat_times: list[float] = []
    if isinstance(raw_beat_times, list):
        for item in raw_beat_times:
            value = _safe_float(item)
            if value is not None:
                beat_times.append(value)
    beat_times = sorted(set(beat_times))
    return _BeatGrid(tempo_bpm=float(tempo_bpm), beat_duration_sec=beat_duration, beat_times=tuple(beat_times))


def _tempo_bpm(rhythm_grid: dict[str, Any] | None) -> float | None:
    if not isinstance(rhythm_grid, dict):
        return None
    for key in ("tempo_bpm", "bpm"):
        value = _safe_float(rhythm_grid.get(key))
        if value and value > 0:
            return float(value)
    return None


def _meter(rhythm_grid: dict[str, Any] | None) -> str | None:
    if not isinstance(rhythm_grid, dict):
        return None
    meter = rhythm_grid.get("meter") or rhythm_grid.get("time_signature")
    if isinstance(meter, str) and meter.strip():
        return meter.strip()
    beats = rhythm_grid.get("beats_per_bar")
    unit = rhythm_grid.get("beat_unit")
    if beats and unit:
        return f"{beats}/{unit}"
    return None


def _pitch_float(note: dict[str, Any]) -> float | None:
    value = _safe_float(note.get("pitch_midi") or note.get("pitch_center_midi") or note.get("pitch_midi_float"))
    if value is not None:
        return value
    pitch = note.get("pitch")
    if isinstance(pitch, str) and pitch.strip():
        try:
            return float(note_to_midi(pitch))
        except Exception:
            return None
    return None


def _safe_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _round_or_none(value: float | None) -> float | None:
    return round(float(value), 6) if value is not None and math.isfinite(float(value)) else None


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    cleaned = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not cleaned:
        return None
    if len(cleaned) == 1:
        return cleaned[0]
    position = (len(cleaned) - 1) * max(0.0, min(1.0, percentile))
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return cleaned[lower]
    return cleaned[lower] + (cleaned[upper] - cleaned[lower]) * (position - lower)


def _safe_ratio(numerator: int | float, denominator: int | float) -> float | None:
    denominator_float = float(denominator)
    if denominator_float == 0.0:
        return None
    return float(numerator) / denominator_float


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
