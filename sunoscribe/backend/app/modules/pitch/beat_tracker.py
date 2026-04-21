from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import numpy as np

from .config import PitchDetectionConfig
from .exceptions import NoBeatsDetectedError


@dataclass
class BeatTrackingResult:
    bpm: float
    beat_times: List[float]
    confidence: float
    raw_bpm: float | None = None
    ioi_bpm: float | None = None
    candidate_bpms: List[float] = field(default_factory=list)
    used_refine: bool = False
    ioi_stability: float | None = None
    local_bpms: List[float] = field(default_factory=list)


@dataclass
class _BpmRefineDecision:
    final_bpm: float
    raw_bpm: float
    ioi_bpm: float | None = None
    candidate_bpms: list[float] = field(default_factory=list)
    used_refine: bool = False
    stability: float = 0.0
    agreement: float = 0.0
    coverage: float = 0.0
    beat_count_factor: float = 0.0
    local_bpms: list[float] = field(default_factory=list)


class BeatTracker:
    """BPM estimation with dynamic IOI refinement."""

    def __init__(self, config: PitchDetectionConfig | None = None) -> None:
        self.config = config or PitchDetectionConfig()

    def track(self, audio_path: str) -> BeatTrackingResult:
        import librosa

        y, sr = librosa.load(audio_path, sr=self.config.sample_rate, mono=True)
        if y.size == 0:
            raise NoBeatsDetectedError("audio is empty; cannot estimate BPM")

        tempo, beat_frames = librosa.beat.beat_track(
            y=y,
            sr=sr,
            start_bpm=self.config.bpm_start_bpm,
            units="frames",
        )
        beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()

        raw_bpm = 0.0
        if tempo is not None:
            raw_bpm = float(np.atleast_1d(tempo)[0])

        audio_duration_sec = float(max(1e-6, y.shape[0] / max(float(sr), 1.0)))
        refine = self._refine_bpm_from_beats(
            raw_bpm=raw_bpm,
            beat_times=beat_times,
            audio_duration_sec=audio_duration_sec,
        )
        final_bpm = float(refine.final_bpm)

        if final_bpm <= 0 or not np.isfinite(final_bpm):
            raise NoBeatsDetectedError("failed to detect a valid BPM")

        beat_strength_conf = 0.2
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        if len(beat_frames) > 0 and len(onset_env) > 0:
            valid_idx = np.clip(beat_frames, 0, len(onset_env) - 1)
            beat_strength = float(np.mean(onset_env[valid_idx]))
            overall_strength = float(np.mean(onset_env) + 1e-8)
            beat_strength_conf = max(0.0, min(1.0, beat_strength / (overall_strength * 2.0)))

        confidence = self._compose_bpm_confidence(beat_strength_conf, refine)

        return BeatTrackingResult(
            bpm=final_bpm,
            beat_times=beat_times,
            confidence=confidence,
            raw_bpm=raw_bpm if raw_bpm > 0 else None,
            ioi_bpm=refine.ioi_bpm,
            candidate_bpms=[float(v) for v in refine.candidate_bpms],
            used_refine=bool(refine.used_refine),
            ioi_stability=float(refine.stability) if refine.ioi_bpm is not None else None,
            local_bpms=[float(v) for v in refine.local_bpms],
        )

    def _compose_bpm_confidence(self, beat_strength_conf: float, refine: _BpmRefineDecision) -> float:
        beat_strength_conf = self._clamp01(beat_strength_conf)
        count_factor = self._clamp01(refine.beat_count_factor)
        coverage = self._clamp01(refine.coverage)

        if refine.ioi_bpm is None:
            return self._clamp01(0.75 * beat_strength_conf + 0.25 * count_factor)

        stability = self._clamp01(refine.stability)
        agreement = self._clamp01(refine.agreement)
        return self._clamp01(
            0.35 * beat_strength_conf
            + 0.25 * stability
            + 0.15 * count_factor
            + 0.15 * coverage
            + 0.10 * agreement
        )

    def _refine_bpm_from_beats(
        self,
        *,
        raw_bpm: float,
        beat_times: List[float],
        audio_duration_sec: float,
    ) -> _BpmRefineDecision:
        raw = float(raw_bpm)
        if not np.isfinite(raw) or raw <= 0:
            return _BpmRefineDecision(final_bpm=raw, raw_bpm=raw)

        decision = _BpmRefineDecision(final_bpm=raw, raw_bpm=raw)
        if not bool(getattr(self.config, "bpm_refine_enabled", True)):
            return decision

        beats = np.asarray(beat_times, dtype=float).reshape(-1)
        beats = beats[np.isfinite(beats)]
        if beats.size >= 2 and audio_duration_sec > 1e-6:
            decision.coverage = self._clamp01((float(beats[-1]) - float(beats[0])) / audio_duration_sec)
        decision.beat_count_factor = self._clamp01((max(0, beats.size - 1)) / 12.0)

        min_beats = max(2, int(getattr(self.config, "bpm_refine_min_beats", 4)))
        if beats.size < min_beats:
            return decision

        intervals = np.diff(beats)
        intervals = intervals[np.isfinite(intervals) & (intervals > 1e-4)]
        min_intervals = max(1, int(getattr(self.config, "bpm_refine_min_intervals", 3)))
        if intervals.size < min_intervals:
            return decision

        if decision.coverage < self._clamp01(float(getattr(self.config, "bpm_refine_min_coverage", 0.25))):
            return decision

        trimmed = self._trim_intervals(intervals)
        if trimmed.size < min_intervals:
            trimmed = intervals
        if trimmed.size < min_intervals:
            return decision

        ioi_median = float(np.median(trimmed))
        if ioi_median <= 1e-4:
            return decision

        mad_ratio = self._mad_ratio(trimmed, ioi_median)
        decision.stability = self._stability_from_mad(mad_ratio)
        if decision.stability <= 0.05:
            return decision

        local_bpms = self._compute_local_bpms(intervals)
        decision.local_bpms = local_bpms

        ioi_bpm_base = 60.0 / ioi_median
        if local_bpms:
            ioi_bpm_base = float(np.median(np.asarray(local_bpms, dtype=float)))

        candidate_bpms = self._build_candidate_bpms(ioi_bpm_base)
        if not candidate_bpms:
            return decision
        decision.candidate_bpms = candidate_bpms

        ioi_selected = self._select_candidate_near_raw(candidate_bpms, raw)
        decision.ioi_bpm = ioi_selected
        decision.agreement = self._agreement_factor(raw=raw, candidate=ioi_selected)

        base_ioi_weight = max(0.0, float(getattr(self.config, "bpm_refine_ioi_weight", 0.85)))
        base_raw_weight = max(0.0, float(getattr(self.config, "bpm_refine_raw_weight", 0.15)))

        ioi_weight = (
            base_ioi_weight
            * decision.stability
            * max(0.2, decision.beat_count_factor)
            * max(0.2, decision.coverage)
            * max(0.0, decision.agreement)
        )
        raw_weight = base_raw_weight

        if decision.agreement < 0.25:
            # Conservative mode when IOI and raw tempo disagree strongly.
            ioi_weight *= 0.2
            raw_weight += base_ioi_weight * 0.5

        total = ioi_weight + raw_weight
        if total <= 1e-8:
            decision.final_bpm = ioi_selected
            decision.used_refine = abs(decision.final_bpm - raw) > 1e-6
            return decision

        decision.final_bpm = (ioi_selected * ioi_weight + raw * raw_weight) / total
        decision.used_refine = abs(decision.final_bpm - raw) > 1e-6
        return decision

    def _trim_intervals(self, intervals: np.ndarray) -> np.ndarray:
        if intervals.size == 0:
            return intervals

        min_for_trim = max(3, int(getattr(self.config, "bpm_refine_min_intervals_for_trim", 12)))
        trim_percent = float(getattr(self.config, "bpm_refine_trim_percent", 10.0))
        trim_percent = max(0.0, min(45.0, trim_percent))

        if intervals.size < min_for_trim or trim_percent <= 0.0:
            return intervals

        lo = float(np.percentile(intervals, trim_percent))
        hi = float(np.percentile(intervals, 100.0 - trim_percent))
        if hi <= lo:
            return intervals

        trimmed = intervals[(intervals >= lo) & (intervals <= hi)]
        if trimmed.size == 0:
            return intervals
        return trimmed

    def _compute_local_bpms(self, intervals: np.ndarray) -> list[float]:
        if intervals.size == 0:
            return []

        window_size = max(2, int(getattr(self.config, "bpm_window_size_intervals", 4)))
        if intervals.size < window_size:
            window_size = int(intervals.size)
        if window_size <= 0:
            return []

        bpm_min = float(getattr(self.config, "bpm_candidate_min", 35.0))
        bpm_max = float(getattr(self.config, "bpm_candidate_max", 260.0))
        local: list[float] = []

        for idx in range(0, intervals.size - window_size + 1):
            patch = intervals[idx : idx + window_size]
            patch = patch[np.isfinite(patch) & (patch > 1e-4)]
            if patch.size == 0:
                continue
            bpm = 60.0 / float(np.median(patch))
            if bpm_min <= bpm <= bpm_max:
                local.append(float(bpm))

        return local

    def _build_candidate_bpms(self, ioi_bpm: float) -> list[float]:
        if not np.isfinite(ioi_bpm) or ioi_bpm <= 0:
            return []

        bpm_min = float(getattr(self.config, "bpm_candidate_min", 35.0))
        bpm_max = float(getattr(self.config, "bpm_candidate_max", 260.0))
        scales = (0.25, 0.5, 1.0, 2.0, 4.0)
        values = [float(ioi_bpm) * scale for scale in scales]

        candidates: list[float] = []
        for value in values:
            if bpm_min <= value <= bpm_max:
                rounded = round(float(value), 6)
                if rounded not in candidates:
                    candidates.append(rounded)

        candidates.sort()
        return candidates

    def _select_candidate_near_raw(self, candidates: list[float], raw: float) -> float:
        if not candidates:
            return raw

        preferred_min = float(getattr(self.config, "bpm_preferred_min", 60.0))
        preferred_max = float(getattr(self.config, "bpm_preferred_max", 200.0))

        if not np.isfinite(raw) or raw <= 0:
            return float(np.median(np.asarray(candidates, dtype=float)))

        def score(value: float) -> float:
            log_dist = abs(float(np.log(max(value, 1e-6) / max(raw, 1e-6))))
            penalty = 0.0
            if value < preferred_min:
                penalty += (preferred_min - value) / max(preferred_min, 1e-6) * 0.2
            elif value > preferred_max:
                penalty += (value - preferred_max) / max(preferred_max, 1e-6) * 0.2
            return log_dist + penalty

        best = min(candidates, key=score)
        return float(best)

    def _agreement_factor(self, *, raw: float, candidate: float) -> float:
        if not np.isfinite(raw) or raw <= 0 or not np.isfinite(candidate) or candidate <= 0:
            return 0.0

        soft = max(1e-6, float(getattr(self.config, "bpm_refine_disagreement_soft", 0.10)))
        hard = max(soft + 1e-6, float(getattr(self.config, "bpm_refine_disagreement_hard", 0.35)))
        log_ratio = abs(float(np.log(candidate / raw)))

        if log_ratio <= soft:
            return 1.0
        if log_ratio >= hard:
            return 0.0
        return self._clamp01((hard - log_ratio) / (hard - soft))

    def _stability_from_mad(self, mad_ratio: float) -> float:
        good = max(1e-6, float(getattr(self.config, "bpm_refine_stability_mad_good", 0.08)))
        bad = max(good + 1e-6, float(getattr(self.config, "bpm_refine_stability_mad_bad", 0.18)))
        if mad_ratio <= good:
            return 1.0
        if mad_ratio >= bad:
            return 0.0
        return self._clamp01((bad - mad_ratio) / (bad - good))

    @staticmethod
    def _mad_ratio(intervals: np.ndarray, center: float) -> float:
        if intervals.size == 0 or center <= 1e-6:
            return 1.0
        mad = float(np.median(np.abs(intervals - center)))
        return mad / center

    @staticmethod
    def _clamp01(value: float) -> float:
        return max(0.0, min(1.0, float(value)))
