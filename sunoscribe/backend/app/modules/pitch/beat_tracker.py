from __future__ import annotations

from dataclasses import dataclass
from typing import List

import numpy as np

from .config import PitchDetectionConfig
from .exceptions import NoBeatsDetectedError


@dataclass
class BeatTrackingResult:
    bpm: float
    beat_times: List[float]
    confidence: float


class BeatTracker:
    """BPM estimation with beat-grid based refinement."""

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

        tempo_raw = 0.0
        if tempo is not None:
            tempo_raw = float(np.atleast_1d(tempo)[0])
        tempo_value = self._refine_bpm_from_beats(raw_bpm=tempo_raw, beat_times=beat_times)

        if tempo_value <= 0 or not np.isfinite(tempo_value):
            raise NoBeatsDetectedError("failed to detect a valid BPM")

        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        if len(beat_frames) > 0 and len(onset_env) > 0:
            valid_idx = np.clip(beat_frames, 0, len(onset_env) - 1)
            beat_strength = float(np.mean(onset_env[valid_idx]))
            overall_strength = float(np.mean(onset_env) + 1e-8)
            confidence = max(0.0, min(1.0, beat_strength / (overall_strength * 2.0)))
        else:
            confidence = 0.2

        return BeatTrackingResult(
            bpm=tempo_value,
            beat_times=beat_times,
            confidence=confidence,
        )

    def _refine_bpm_from_beats(self, *, raw_bpm: float, beat_times: List[float]) -> float:
        raw = float(raw_bpm)
        if not np.isfinite(raw) or raw <= 0:
            return raw

        if not bool(getattr(self.config, "bpm_refine_enabled", True)):
            return raw

        if len(beat_times) < 3:
            return raw

        intervals = np.diff(np.asarray(beat_times, dtype=float))
        intervals = intervals[np.isfinite(intervals) & (intervals > 1e-4)]
        if intervals.size < 2:
            return raw

        # Robust IOI estimate: trim 10% tails, then use median.
        trim_percent = float(getattr(self.config, "bpm_refine_trim_percent", 10.0))
        trim_percent = max(0.0, min(45.0, trim_percent))
        lo = float(np.percentile(intervals, trim_percent))
        hi = float(np.percentile(intervals, 100.0 - trim_percent))
        trimmed = intervals[(intervals >= lo) & (intervals <= hi)]
        if trimmed.size == 0:
            trimmed = intervals

        ioi_median = float(np.median(trimmed))
        if ioi_median <= 1e-4:
            return raw
        bpm_from_ioi = 60.0 / ioi_median

        # Resolve obvious half/double ambiguity around raw tempo.
        while bpm_from_ioi < raw * 0.6:
            bpm_from_ioi *= 2.0
        while bpm_from_ioi > raw * 1.8:
            bpm_from_ioi *= 0.5

        # Hybrid estimate: configurable blend between beat-grid IOI and raw tempo.
        ioi_weight = max(0.0, float(getattr(self.config, "bpm_refine_ioi_weight", 0.8)))
        raw_weight = max(0.0, float(getattr(self.config, "bpm_refine_raw_weight", 0.2)))
        total_weight = ioi_weight + raw_weight
        if total_weight <= 1e-8:
            return float(bpm_from_ioi)

        refined = (bpm_from_ioi * ioi_weight + raw * raw_weight) / total_weight
        return float(refined)
