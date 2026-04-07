from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from .config import PitchDetectionConfig
from .exceptions import DownbeatTrackingError


@dataclass
class DownbeatTrackingResult:
    downbeat_times: list[float]
    method: str
    confidence: float
    beats_per_bar: int


class DownbeatTracker:
    """真实 downbeat 检测（madmom 优先，librosa 降级）。"""

    def __init__(self, config: PitchDetectionConfig | None = None) -> None:
        self.config = config or PitchDetectionConfig()

    def track(self, audio_path: str, beat_times: Sequence[float] | None = None) -> DownbeatTrackingResult:
        backend = (self.config.downbeat_backend or "librosa").lower()
        if backend == "madmom":
            try:
                return self._track_madmom(audio_path)
            except Exception:
                return self._track_librosa(audio_path, beat_times, method="librosa_fallback")
        return self._track_librosa(audio_path, beat_times, method="librosa")

    def _track_librosa(
        self,
        audio_path: str,
        beat_times: Sequence[float] | None,
        method: str,
    ) -> DownbeatTrackingResult:
        import librosa

        y, sr = librosa.load(audio_path, sr=self.config.sample_rate, mono=True)

        if beat_times is None or len(beat_times) == 0:
            _, beat_frames = librosa.beat.beat_track(y=y, sr=sr, units="frames")
            beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()

        beats = list(float(t) for t in beat_times)
        bpb = max(2, int(self.config.beats_per_bar))

        if len(beats) < bpb:
            raise DownbeatTrackingError("节拍点不足，无法推断 downbeat。")

        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        beat_frames = librosa.time_to_frames(np.array(beats), sr=sr)
        beat_frames = np.clip(beat_frames, 0, max(0, len(onset_env) - 1))
        strengths = onset_env[beat_frames] if len(onset_env) else np.zeros(len(beats))

        offset_scores = []
        for offset in range(bpb):
            vals = strengths[offset::bpb]
            offset_scores.append(float(np.mean(vals)) if len(vals) else 0.0)

        best_offset = int(np.argmax(offset_scores))
        downbeats = beats[best_offset::bpb]

        overall = float(np.mean(strengths) + 1e-8)
        best = float(offset_scores[best_offset] + 1e-8)
        confidence = max(0.0, min(1.0, best / (overall * 1.8)))

        return DownbeatTrackingResult(
            downbeat_times=downbeats,
            method=method,
            confidence=confidence,
            beats_per_bar=bpb,
        )

    def _track_madmom(self, audio_path: str) -> DownbeatTrackingResult:
        from madmom.features.downbeats import DBNDownBeatTrackingProcessor, RNNDownBeatProcessor

        bpb = max(2, int(self.config.beats_per_bar))
        act = RNNDownBeatProcessor()(audio_path)
        proc = DBNDownBeatTrackingProcessor(beats_per_bar=[bpb], fps=100)
        tracking = proc(act)

        downbeats = [float(row[0]) for row in tracking if int(round(row[1])) == 1]
        if not downbeats:
            raise DownbeatTrackingError("madmom 未检测到 downbeat。")

        return DownbeatTrackingResult(
            downbeat_times=downbeats,
            method="madmom",
            confidence=0.9,
            beats_per_bar=bpb,
        )
