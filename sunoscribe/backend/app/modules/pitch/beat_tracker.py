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
    """基于 librosa 的 BPM 检测。"""

    def __init__(self, config: PitchDetectionConfig | None = None) -> None:
        self.config = config or PitchDetectionConfig()

    def track(self, audio_path: str) -> BeatTrackingResult:
        import librosa

        y, sr = librosa.load(audio_path, sr=self.config.sample_rate, mono=True)
        if y.size == 0:
            raise NoBeatsDetectedError("音频为空，无法检测 BPM。")

        tempo, beat_frames = librosa.beat.beat_track(
            y=y,
            sr=sr,
            start_bpm=self.config.bpm_start_bpm,
            units="frames",
        )
        tempo_value = float(np.atleast_1d(tempo)[0])
        beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()

        if tempo is None or tempo_value <= 0:
            raise NoBeatsDetectedError("未检测到有效 BPM。")

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
