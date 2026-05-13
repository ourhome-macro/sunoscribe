from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
from typing import Any

from .note_utils import midi_to_note, note_to_midi
from .reason_codes import (
    BRIDGE_FROM_F0_CONTOUR,
    BRIDGE_OVERLAPS_RAW_CANDIDATE,
    BRIDGE_UNSTABLE_CONTOUR_GUARDED,
    BRIDGE_VOCAL_ACTIVITY_UNSUPPORTED,
    CONTOUR_CANDIDATE_CONTEXT_GUARDED,
    CONTOUR_CANDIDATE_NO_LOCAL_CONTEXT,
    CONTOUR_CANDIDATE_NO_RAW_GAP,
    CONTOUR_CANDIDATE_SPLITS_BIG_GAP,
    CONTOUR_TO_CANDIDATE_BRIDGE,
    LOW_CONFIDENCE,
    LOW_VOICED_RATIO,
    OCTAVE_OUTLIER,
    OUTSIDE_VOCAL_RANGE,
    PRESELECTOR_LOW_OCTAVE_CORRECTED,
    TOO_SHORT,
    TOO_UNSTABLE,
)
from .types import Note, VocalActivitySegment


@dataclass(frozen=True)
class ContourToCandidateBridgeConfig:
    enabled: bool = True
    min_confidence: float = 0.72
    min_voiced_ratio: float = 0.9
    min_duration_sec: float = 0.18
    max_duration_sec: float = 2.5
    min_stability: float = 0.35
    vocal_min_midi: float = 48.0
    vocal_max_midi: float = 84.0
    min_vocal_activity_overlap_ratio: float = 0.6
    max_raw_overlap_sec: float = 0.0
    min_raw_gap_sec: float = 0.18
    context_gap_sec: float = 4.0
    big_gap_sec: float = 0.5
    low_octave_context_tolerance_semitones: int = 4


@dataclass(frozen=True)
class ContourToCandidateBridgeResult:
    notes: list[Note]
    accepted_candidates: list[dict[str, Any]]
    rejected_candidates: list[dict[str, Any]]
    summary: dict[str, Any]


class ContourToCandidateBridge:
    """Conservatively promote isolated high-quality F0 contours into raw candidates."""

    def __init__(self, config: ContourToCandidateBridgeConfig | None = None) -> None:
        self.config = config or ContourToCandidateBridgeConfig()

    def bridge(
        self,
        *,
        contours: list[dict[str, Any]] | None,
        raw_candidates: list[Note],
        vocal_activity: list[VocalActivitySegment] | None = None,
    ) -> ContourToCandidateBridgeResult:
        contour_items = [item for item in contours or [] if isinstance(item, dict)]
        summary: dict[str, Any] = {
            "version": "contour_to_candidate_bridge_v1",
            "enabled": bool(self.config.enabled),
            "candidate_count": len(contour_items),
            "accepted_count": 0,
            "rejected_count": 0,
            "guard_reason_counts": {},
            "accepted_candidates": [],
            "rejected_candidates": [],
        }
        if not self.config.enabled or not contour_items or not raw_candidates:
            return ContourToCandidateBridgeResult(
                notes=list(raw_candidates or []),
                accepted_candidates=[],
                rejected_candidates=[],
                summary=summary,
            )

        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        guard_counts: Counter[str] = Counter()
        working_notes = list(raw_candidates)
        vocal_segments = list(vocal_activity or [])

        for index, contour in enumerate(contour_items, start=1):
            candidate = self._candidate_from_contour(contour, index)
            evidence = self._evidence(
                candidate=candidate,
                contour=contour,
                raw_candidates=working_notes,
                vocal_segments=vocal_segments,
            )
            guard_reasons = self._guard_reasons(candidate, evidence, vocal_segments_available=bool(vocal_segments))
            candidate["contour_bridge_evidence"] = evidence
            candidate["contour_bridge_guard_reason_codes"] = guard_reasons
            if guard_reasons:
                rejected_item = self._summary_item(candidate)
                rejected.append(rejected_item)
                for reason in guard_reasons:
                    guard_counts[reason] += 1
                continue

            note = self._note_from_candidate(candidate)
            working_notes.append(note)
            accepted_item = self._summary_item(candidate)
            accepted.append(accepted_item)
            guard_counts[CONTOUR_CANDIDATE_CONTEXT_GUARDED] += 1

        summary["accepted_count"] = len(accepted)
        summary["rejected_count"] = len(rejected)
        summary["guard_reason_counts"] = dict(sorted(guard_counts.items()))
        summary["accepted_candidates"] = accepted
        summary["rejected_candidates"] = rejected
        return ContourToCandidateBridgeResult(
            notes=sorted(working_notes, key=lambda note: (float(note.start_time), float(note.end_time), str(note.pitch))),
            accepted_candidates=accepted,
            rejected_candidates=rejected,
            summary=summary,
        )

    def _candidate_from_contour(self, contour: dict[str, Any], index: int) -> dict[str, Any]:
        source_id = str(contour.get("id") or f"pc_{index:05d}")
        start = _safe_float(_first(contour, "start_time_sec", "start_time", "start")) or 0.0
        end = _safe_float(_first(contour, "end_time_sec", "end_time", "end"))
        duration = _safe_float(_first(contour, "duration_sec", "duration"))
        if end is None and duration is not None:
            end = start + duration
        if end is None:
            end = start
        pitch_center = _pitch_center(contour)
        confidence = _safe_float(contour.get("mean_confidence"))
        if confidence is None:
            confidence = _safe_float(contour.get("confidence")) or 0.0
        return {
            "candidate_id": f"contour_bridge:{source_id}",
            "source_contour_id": source_id,
            "start_time_sec": round(float(start), 6),
            "end_time_sec": round(float(end), 6),
            "duration_sec": round(max(0.0, float(end) - float(start)), 6),
            "pitch_center_midi": _round_optional(pitch_center),
            "confidence": round(max(0.0, min(1.0, float(confidence))), 6),
            "voiced_ratio": _round_optional(contour.get("voiced_ratio")),
            "stability": _round_optional(contour.get("stability")),
            "has_glide": bool(contour.get("has_glide")),
            "has_vibrato": bool(contour.get("has_vibrato")),
            "source_contour_reason_codes": [str(item) for item in contour.get("reason_codes") or []],
            "reason_codes": [
                CONTOUR_TO_CANDIDATE_BRIDGE,
                BRIDGE_FROM_F0_CONTOUR,
                CONTOUR_CANDIDATE_CONTEXT_GUARDED,
            ],
            "source_contour_ids": [source_id],
            "source_candidate_ids": [],
        }

    def _evidence(
        self,
        *,
        candidate: dict[str, Any],
        contour: dict[str, Any],
        raw_candidates: list[Note],
        vocal_segments: list[VocalActivitySegment],
    ) -> dict[str, Any]:
        start = float(candidate["start_time_sec"])
        end = float(candidate["end_time_sec"])
        duration = max(0.0, end - start)
        raw_overlap = _max_note_overlap_duration(raw_candidates, start, end)
        raw_gaps = _raw_gaps(raw_candidates)
        nearest_gap = _nearest_gap(raw_gaps, start, end)
        nearest_gap_overlap = (
            _overlap_seconds(start, end, float(nearest_gap["start_time_sec"]), float(nearest_gap["end_time_sec"]))
            if nearest_gap is not None
            else 0.0
        )
        context = self._local_context(candidate, raw_candidates=raw_candidates)
        vocal_overlap = _vocal_activity_overlap(vocal_segments, start, end)
        source_start = _safe_float(_first(contour, "start_time_sec", "start_time", "start"))
        source_end = _safe_float(_first(contour, "end_time_sec", "end_time", "end"))
        return {
            "source_contour_id": str(candidate["source_contour_id"]),
            "source_start_time_sec": round(float(source_start), 6) if source_start is not None else round(start, 6),
            "source_end_time_sec": round(float(source_end), 6) if source_end is not None else round(end, 6),
            "candidate_start_time_sec": round(start, 6),
            "candidate_end_time_sec": round(end, 6),
            "candidate_duration_sec": round(duration, 6),
            "pitch_center_midi": candidate.get("pitch_center_midi"),
            "mean_confidence": round(float(candidate.get("confidence") or 0.0), 6),
            "voiced_ratio": candidate.get("voiced_ratio"),
            "stability": candidate.get("stability"),
            "has_glide": bool(candidate.get("has_glide")),
            "has_vibrato": bool(candidate.get("has_vibrato")),
            "nearest_raw_gap": nearest_gap,
            "nearest_raw_gap_overlap_duration_sec": round(nearest_gap_overlap, 6),
            "raw_overlap_duration_sec": round(raw_overlap, 6),
            "selected_context_overlap_duration_sec": round(raw_overlap, 6),
            "vocal_activity_overlap_ratio": round(vocal_overlap / duration, 6) if duration > 0.0 else 0.0,
            "vocal_activity_available": bool(vocal_segments),
            "left_context_candidate_id": context.get("left_candidate_id"),
            "left_context_pitch_midi": context.get("left_pitch_midi"),
            "left_context_gap_sec": context.get("left_gap_sec"),
            "right_context_candidate_id": context.get("right_candidate_id"),
            "right_context_pitch_midi": context.get("right_pitch_midi"),
            "right_context_gap_sec": context.get("right_gap_sec"),
            "applied_guard_reason_codes": [],
            "source_contour_reason_codes": list(candidate.get("source_contour_reason_codes") or []),
        }

    def _guard_reasons(
        self,
        candidate: dict[str, Any],
        evidence: dict[str, Any],
        *,
        vocal_segments_available: bool,
    ) -> list[str]:
        reasons: list[str] = []
        duration = float(candidate.get("duration_sec") or 0.0)
        confidence = float(candidate.get("confidence") or 0.0)
        pitch = _safe_float(candidate.get("pitch_center_midi"))
        voiced_ratio = _safe_float(candidate.get("voiced_ratio"))
        stability = _safe_float(candidate.get("stability"))

        if confidence < float(self.config.min_confidence):
            reasons.append(LOW_CONFIDENCE)
        if voiced_ratio is None or voiced_ratio < float(self.config.min_voiced_ratio):
            reasons.append(LOW_VOICED_RATIO)
        if duration < float(self.config.min_duration_sec):
            reasons.append(TOO_SHORT)
        if duration > float(self.config.max_duration_sec):
            reasons.append(TOO_UNSTABLE)
        octave_evidence = None
        if pitch is not None and pitch < float(self.config.vocal_min_midi):
            octave_evidence = self._maybe_correct_low_octave(candidate, evidence)
            if octave_evidence is not None:
                pitch = _safe_float(candidate.get("pitch_center_midi"))
                evidence["octave_correction"] = octave_evidence
                evidence["pitch_center_midi"] = candidate.get("pitch_center_midi")

        if pitch is None or not (float(self.config.vocal_min_midi) <= pitch <= float(self.config.vocal_max_midi)):
            reasons.append(OUTSIDE_VOCAL_RANGE)
        if stability is None or stability < float(self.config.min_stability):
            reasons.append(TOO_UNSTABLE)
        if float(evidence.get("raw_overlap_duration_sec") or 0.0) > float(self.config.max_raw_overlap_sec):
            reasons.append(BRIDGE_OVERLAPS_RAW_CANDIDATE)
        nearest_gap = evidence.get("nearest_raw_gap") if isinstance(evidence.get("nearest_raw_gap"), dict) else None
        nearest_gap_overlap = float(evidence.get("nearest_raw_gap_overlap_duration_sec") or 0.0)
        if (
            nearest_gap is None
            or float(nearest_gap.get("duration_sec") or 0.0) < float(self.config.min_raw_gap_sec)
            or nearest_gap_overlap < float(self.config.min_duration_sec)
        ):
            reasons.append(CONTOUR_CANDIDATE_NO_RAW_GAP)
        if evidence.get("left_context_pitch_midi") is None or evidence.get("right_context_pitch_midi") is None:
            reasons.append(CONTOUR_CANDIDATE_NO_LOCAL_CONTEXT)
        if self._splits_big_gap(evidence):
            reasons.append(CONTOUR_CANDIDATE_SPLITS_BIG_GAP)
        if (
            vocal_segments_available
            and float(evidence.get("vocal_activity_overlap_ratio") or 0.0)
            < float(self.config.min_vocal_activity_overlap_ratio)
        ):
            reasons.append(BRIDGE_VOCAL_ACTIVITY_UNSUPPORTED)

        reasons = _unique(reasons)
        if TOO_UNSTABLE in reasons and (candidate.get("has_glide") or candidate.get("has_vibrato")) and len(reasons) == 1:
            candidate["reason_codes"] = _unique(list(candidate.get("reason_codes") or []) + [BRIDGE_UNSTABLE_CONTOUR_GUARDED])
            reasons = []
        if not reasons:
            applied = list(candidate.get("reason_codes") or [])
            evidence["applied_guard_reason_codes"] = applied
            return []

        evidence["applied_guard_reason_codes"] = list(candidate.get("reason_codes") or [])
        return reasons

    def _maybe_correct_low_octave(self, candidate: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any] | None:
        pitch = _safe_float(candidate.get("pitch_center_midi"))
        if pitch is None or pitch >= float(self.config.vocal_min_midi):
            return None
        left_pitch = _safe_float(evidence.get("left_context_pitch_midi"))
        right_pitch = _safe_float(evidence.get("right_context_pitch_midi"))
        context_pitches = [item for item in (left_pitch, right_pitch) if item is not None]
        if not context_pitches:
            return None
        shifted = pitch + 12.0
        if shifted < float(self.config.vocal_min_midi) or shifted > float(self.config.vocal_max_midi):
            return None
        current_delta = min(abs(pitch - context_pitch) for context_pitch in context_pitches)
        shifted_delta = min(abs(shifted - context_pitch) for context_pitch in context_pitches)
        tolerance = max(1, int(self.config.low_octave_context_tolerance_semitones))
        if current_delta < 8.0 or shifted_delta > float(tolerance):
            return None
        if shifted_delta + max(2.0, float(tolerance) / 2.0) >= current_delta:
            return None
        candidate["pitch_center_midi"] = round(shifted, 6)
        candidate["reason_codes"] = _unique(
            list(candidate.get("reason_codes") or [])
            + [OCTAVE_OUTLIER, PRESELECTOR_LOW_OCTAVE_CORRECTED]
        )
        return {
            "original_pitch": round(pitch, 6),
            "shift": 12,
            "corrected_pitch": round(shifted, 6),
            "left_context_pitch": left_pitch,
            "right_context_pitch": right_pitch,
        }

    def _splits_big_gap(self, evidence: dict[str, Any]) -> bool:
        nearest_gap = evidence.get("nearest_raw_gap") if isinstance(evidence.get("nearest_raw_gap"), dict) else None
        if nearest_gap is None:
            return False
        big_gap = max(0.0, float(self.config.big_gap_sec))
        original_gap = float(nearest_gap.get("duration_sec") or 0.0)
        if original_gap <= big_gap:
            return False
        left_gap = float(evidence.get("left_context_gap_sec") or -1.0)
        right_gap = float(evidence.get("right_context_gap_sec") or -1.0)
        if left_gap < 0.0 or right_gap < 0.0:
            return True
        after_big_count = int(left_gap > big_gap) + int(right_gap > big_gap)
        return after_big_count > 1

    def _local_context(self, candidate: dict[str, Any], *, raw_candidates: list[Note]) -> dict[str, Any]:
        start = float(candidate["start_time_sec"])
        end = float(candidate["end_time_sec"])
        max_gap = max(0.0, float(self.config.context_gap_sec))
        min_pitch = float(self.config.vocal_min_midi)
        max_pitch = float(self.config.vocal_max_midi)
        left: tuple[float, Note] | None = None
        right: tuple[float, Note] | None = None
        for note in raw_candidates:
            pitch = _note_pitch_midi(note)
            if pitch is None or not (min_pitch <= pitch <= max_pitch):
                continue
            duration = max(0.0, float(note.end_time) - float(note.start_time))
            if duration < float(self.config.min_duration_sec):
                continue
            if float(note.confidence) < float(self.config.min_confidence):
                continue
            note_end = float(note.end_time)
            note_start = float(note.start_time)
            if note_end <= start:
                gap = start - note_end
                if gap <= max_gap and (left is None or gap < left[0]):
                    left = (gap, note)
            elif note_start >= end:
                gap = note_start - end
                if gap <= max_gap and (right is None or gap < right[0]):
                    right = (gap, note)
        return {
            "left_candidate_id": _note_candidate_id(left[1]) if left else None,
            "left_pitch_midi": _round_optional(_note_pitch_midi(left[1])) if left else None,
            "left_gap_sec": round(float(left[0]), 6) if left else None,
            "right_candidate_id": _note_candidate_id(right[1]) if right else None,
            "right_pitch_midi": _round_optional(_note_pitch_midi(right[1])) if right else None,
            "right_gap_sec": round(float(right[0]), 6) if right else None,
        }

    def _note_from_candidate(self, candidate: dict[str, Any]) -> Note:
        pitch_center = _safe_float(candidate.get("pitch_center_midi"))
        pitch_name = midi_to_note(pitch_center if pitch_center is not None else 60.0)
        return Note(
            pitch=pitch_name,
            start_time=float(candidate["start_time_sec"]),
            end_time=float(candidate["end_time_sec"]),
            confidence=float(candidate["confidence"]),
            reason_codes=list(candidate.get("reason_codes") or []),
            candidate_id=str(candidate["candidate_id"]),
            source_candidate_id=str(candidate["candidate_id"]),
            source_contour_ids=list(candidate.get("source_contour_ids") or []),
            contour_bridge_evidence=dict(candidate.get("contour_bridge_evidence") or {}),
            contour_bridge_guard_reason_codes=list(candidate.get("contour_bridge_guard_reason_codes") or []),
            candidate_origin=CONTOUR_TO_CANDIDATE_BRIDGE,
        )

    @staticmethod
    def _summary_item(candidate: dict[str, Any]) -> dict[str, Any]:
        return {
            "candidate_id": candidate.get("candidate_id"),
            "source_contour_id": candidate.get("source_contour_id"),
            "start_time_sec": candidate.get("start_time_sec"),
            "end_time_sec": candidate.get("end_time_sec"),
            "duration_sec": candidate.get("duration_sec"),
            "pitch_center_midi": candidate.get("pitch_center_midi"),
            "confidence": candidate.get("confidence"),
            "reason_codes": list(candidate.get("reason_codes") or []),
            "contour_bridge_guard_reason_codes": list(candidate.get("contour_bridge_guard_reason_codes") or []),
            "evidence": dict(candidate.get("contour_bridge_evidence") or {}),
        }


def _raw_gaps(notes: list[Note]) -> list[dict[str, Any]]:
    ordered = sorted(notes, key=lambda note: (float(note.start_time), float(note.end_time), str(note.pitch)))
    gaps: list[dict[str, Any]] = []
    for left, right in zip(ordered, ordered[1:]):
        start = float(left.end_time)
        end = float(right.start_time)
        if end <= start:
            continue
        gaps.append(
            {
                "start_time_sec": round(start, 6),
                "end_time_sec": round(end, 6),
                "duration_sec": round(end - start, 6),
                "left_candidate_id": _note_candidate_id(left),
                "right_candidate_id": _note_candidate_id(right),
            }
        )
    return gaps


def _nearest_gap(gaps: list[dict[str, Any]], start: float, end: float) -> dict[str, Any] | None:
    if not gaps:
        return None
    midpoint = (float(start) + float(end)) / 2.0
    ranked = sorted(
        gaps,
        key=lambda gap: (
            0 if float(gap["start_time_sec"]) <= midpoint <= float(gap["end_time_sec"]) else 1,
            abs(((float(gap["start_time_sec"]) + float(gap["end_time_sec"])) / 2.0) - midpoint),
        ),
    )
    return dict(ranked[0])


def _max_note_overlap_duration(notes: list[Note], start: float, end: float) -> float:
    return max(
        (
            _overlap_seconds(float(note.start_time), float(note.end_time), start, end)
            for note in notes
        ),
        default=0.0,
    )


def _vocal_activity_overlap(segments: list[VocalActivitySegment], start: float, end: float) -> float:
    total = 0.0
    for segment in segments:
        state = str(getattr(segment, "state", "") or "").strip().lower()
        if state not in {"vocal", "voiced", "voice", "transition", "climax"}:
            continue
        total += _overlap_seconds(float(segment.start_time), float(segment.end_time), start, end)
    return total


def _note_candidate_id(note: Note) -> str:
    return str(getattr(note, "candidate_id", None) or getattr(note, "source_candidate_id", None) or f"{note.pitch}:{note.start_time:.6f}:{note.end_time:.6f}")


def _note_pitch_midi(note: Note) -> float | None:
    try:
        return float(note_to_midi(str(note.pitch)))
    except Exception:
        return None


def _pitch_center(payload: dict[str, Any]) -> float | None:
    value = _safe_float(_first(payload, "pitch_center_midi", "median_midi", "mean_midi", "midi_float", "pitch_midi"))
    if value is not None:
        return value
    frequency = _safe_float(_first(payload, "f0_hz", "frequency_hz", "frequency"))
    if frequency is not None and frequency > 0.0:
        return 69.0 + 12.0 * math.log2(frequency / 440.0)
    pitch = payload.get("pitch") or payload.get("pitch_name")
    if isinstance(pitch, str) and pitch.strip():
        try:
            return float(note_to_midi(pitch))
        except Exception:
            return None
    return None


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
    return result if math.isfinite(result) else None


def _round_optional(value: Any) -> float | None:
    parsed = _safe_float(value)
    return round(parsed, 6) if parsed is not None else None


def _overlap_seconds(left_start: float, left_end: float, right_start: float, right_end: float) -> float:
    return max(0.0, min(float(left_end), float(right_end)) - max(float(left_start), float(right_start)))


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result
