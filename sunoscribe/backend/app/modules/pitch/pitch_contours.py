from __future__ import annotations

from dataclasses import dataclass
import math
from statistics import median
from typing import Any

from .reason_codes import LOW_CONFIDENCE, LOW_VOICED_RATIO, SUSPECTED_GLIDE, SUSPECTED_VIBRATO, TOO_SHORT, TOO_UNSTABLE, UNCERTAIN


@dataclass(frozen=True)
class PitchContourConfig:
    min_confidence: float = 0.35
    low_confidence_threshold: float = 0.5
    max_unvoiced_gap_sec: float = 0.04
    min_duration_sec: float = 0.04
    stable_extent_cents: float = 80.0
    glide_extent_cents: float = 250.0
    vibrato_min_turns: int = 4
    vibrato_min_extent_cents: float = 25.0
    vibrato_max_extent_cents: float = 180.0


class PitchContourBuilder:
    def __init__(self, config: PitchContourConfig | None = None) -> None:
        self.config = config or PitchContourConfig()

    def build(self, f0_track: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(f0_track, dict):
            return None
        frames = f0_track.get("frames")
        if not isinstance(frames, list):
            return None

        normalized = [frame for frame in (self._normalize_frame(raw) for raw in frames) if frame is not None]
        segments = self._segment_frames(normalized)
        contours = [self._build_contour(segment, index) for index, segment in enumerate(segments, start=1)]
        return {
            "version": "pitch_contours_v1",
            "source_f0_track": f0_track.get("backend") or f0_track.get("source_stem") or "f0_track",
            "contours": contours,
            "summary": self._summary(contours),
        }

    def _normalize_frame(self, frame: Any) -> dict[str, Any] | None:
        if not isinstance(frame, dict):
            return None
        time_sec = _safe_float(_first(frame, "time_sec", "time"))
        if time_sec is None:
            return None
        midi_float = _safe_float(_first(frame, "midi_float", "pitch_midi", "midi"))
        f0_hz = _safe_float(_first(frame, "f0_hz", "frequency_hz", "frequency", "f0"))
        if midi_float is None and f0_hz is not None and f0_hz > 0:
            midi_float = 69.0 + 12.0 * math.log2(f0_hz / 440.0)
        confidence = _safe_float(frame.get("confidence"))
        voiced = frame.get("voiced")
        if voiced is None:
            voiced = bool(midi_float is not None and (confidence is None or confidence >= self.config.min_confidence))
        return {
            "time_sec": float(time_sec),
            "midi_float": midi_float,
            "f0_hz": f0_hz,
            "confidence": confidence,
            "voiced": bool(voiced),
        }

    def _segment_frames(self, frames: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        segments: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        gap_buffer: list[dict[str, Any]] = []
        for frame in frames:
            active = self._is_active(frame)
            if active:
                if current and gap_buffer:
                    gap = frame["time_sec"] - gap_buffer[0]["time_sec"]
                    if gap <= self.config.max_unvoiced_gap_sec:
                        current.extend(gap_buffer)
                    else:
                        segments.append(current)
                        current = []
                    gap_buffer = []
                current.append(frame)
                continue

            if current:
                gap_buffer.append(frame)
                last_active = current[-1]["time_sec"]
                if frame["time_sec"] - last_active > self.config.max_unvoiced_gap_sec:
                    segments.append(current)
                    current = []
                    gap_buffer = []

        if current:
            segments.append(current)
        return segments

    def _is_active(self, frame: dict[str, Any]) -> bool:
        confidence = frame.get("confidence")
        if confidence is None:
            confidence_ok = True
        else:
            confidence_ok = float(confidence) >= self.config.min_confidence
        return bool(frame.get("voiced")) and frame.get("midi_float") is not None and confidence_ok

    def _build_contour(self, frames: list[dict[str, Any]], index: int) -> dict[str, Any]:
        times = [float(frame["time_sec"]) for frame in frames]
        active_frames = [frame for frame in frames if frame.get("midi_float") is not None]
        midi_values = [float(frame["midi_float"]) for frame in active_frames]
        confidence_values = [float(frame["confidence"]) for frame in active_frames if frame.get("confidence") is not None]
        start = min(times)
        end = max(times)
        if len(times) >= 2:
            hop = median([b - a for a, b in zip(sorted(times), sorted(times)[1:]) if b > a] or [0.0])
        else:
            hop = 0.0
        end = max(end + max(0.0, float(hop)), end)
        duration = max(0.0, end - start)
        min_midi = min(midi_values) if midi_values else None
        max_midi = max(midi_values) if midi_values else None
        extent_cents = (max_midi - min_midi) * 100.0 if min_midi is not None and max_midi is not None else 0.0
        mean_midi = sum(midi_values) / len(midi_values) if midi_values else None
        median_midi = float(median(midi_values)) if midi_values else None
        mean_confidence = sum(confidence_values) / len(confidence_values) if confidence_values else 0.0
        max_confidence = max(confidence_values) if confidence_values else 0.0
        voiced_ratio = len(active_frames) / max(1, len(frames))
        stability = max(0.0, min(1.0, 1.0 - (extent_cents / 300.0)))
        turns = _turn_count(midi_values)
        has_vibrato = turns >= self.config.vibrato_min_turns and self.config.vibrato_min_extent_cents <= extent_cents <= self.config.vibrato_max_extent_cents
        has_glide = extent_cents >= self.config.glide_extent_cents
        reason_codes: list[str] = []
        if duration < self.config.min_duration_sec:
            reason_codes.append(TOO_SHORT)
        if mean_confidence < self.config.low_confidence_threshold:
            reason_codes.append(LOW_CONFIDENCE)
        if voiced_ratio < 0.8:
            reason_codes.append(LOW_VOICED_RATIO)
        if stability < 0.5:
            reason_codes.append(TOO_UNSTABLE)
        if has_vibrato:
            reason_codes.append(SUSPECTED_VIBRATO)
        if has_glide:
            reason_codes.append(SUSPECTED_GLIDE)
        if reason_codes:
            reason_codes.append(UNCERTAIN)
        return {
            "id": f"pc_{index:05d}",
            "start_time_sec": round(start, 6),
            "end_time_sec": round(end, 6),
            "duration_sec": round(duration, 6),
            "frame_count": len(frames),
            "median_midi": _round_or_none(median_midi),
            "mean_midi": _round_or_none(mean_midi),
            "pitch_center_midi": _round_or_none(median_midi),
            "min_midi": _round_or_none(min_midi),
            "max_midi": _round_or_none(max_midi),
            "voiced_ratio": round(voiced_ratio, 6),
            "mean_confidence": round(mean_confidence, 6),
            "max_confidence": round(max_confidence, 6),
            "stability": round(stability, 6),
            "vibrato_rate_hz": _round_or_none(_estimate_vibrato_rate(turns, duration) if has_vibrato else None),
            "vibrato_extent_cents": _round_or_none(extent_cents if has_vibrato else None),
            "has_vibrato": bool(has_vibrato),
            "has_glide": bool(has_glide),
            "frame_samples": _frame_samples(frames),
            "source": "f0_track",
            "reason_codes": _unique(reason_codes),
        }

    @staticmethod
    def _summary(contours: list[dict[str, Any]]) -> dict[str, Any]:
        durations = [float(item.get("duration_sec") or 0.0) for item in contours]
        return {
            "contour_count": len(contours),
            "low_confidence_contour_count": sum(1 for item in contours if LOW_CONFIDENCE in item.get("reason_codes", [])),
            "median_contour_duration_sec": round(float(median(durations)), 6) if durations else 0.0,
            "suspected_vibrato_contour_count": sum(1 for item in contours if item.get("has_vibrato")),
            "suspected_glide_contour_count": sum(1 for item in contours if item.get("has_glide")),
        }


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


def _round_or_none(value: float | None) -> float | None:
    return round(float(value), 6) if value is not None and math.isfinite(float(value)) else None


def _frame_samples(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for frame in frames:
        time_sec = _safe_float(frame.get("time_sec"))
        if time_sec is None:
            continue
        samples.append(
            {
                "time_sec": round(float(time_sec), 6),
                "pitch_midi": _round_or_none(_safe_float(frame.get("midi_float"))),
                "confidence": _round_or_none(_safe_float(frame.get("confidence"))),
                "voiced": bool(frame.get("voiced")),
            }
        )
    return samples


def _turn_count(values: list[float]) -> int:
    if len(values) < 3:
        return 0
    signs: list[int] = []
    for left, right in zip(values, values[1:]):
        delta = right - left
        if abs(delta) < 0.03:
            continue
        signs.append(1 if delta > 0 else -1)
    return sum(1 for left, right in zip(signs, signs[1:]) if left != right)


def _estimate_vibrato_rate(turns: int, duration: float) -> float | None:
    if duration <= 0 or turns <= 1:
        return None
    cycles = turns / 2.0
    return cycles / duration


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
