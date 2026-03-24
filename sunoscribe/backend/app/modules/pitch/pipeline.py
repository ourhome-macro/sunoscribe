from __future__ import annotations

import librosa

from .beat_tracker import BeatTracker
from .config import PitchDetectionConfig
from .detector import PitchDetector
from .key_analyzer import KeyAnalyzer
from .types import MetaInfo, PitchAnalysisResult


class PitchPipeline:
    """
    P0 流水线：
    - 原始音符序列（basic-pitch）
    - BPM（librosa）
    - 调式（librosa chroma）
    """

    VERSION = "1.0"

    def __init__(self, config: PitchDetectionConfig | None = None) -> None:
        self.config = config or PitchDetectionConfig()
        self.detector = PitchDetector(self.config)
        self.beat_tracker = BeatTracker(self.config)
        self.key_analyzer = KeyAnalyzer(self.config)

    def run(self, audio_path: str) -> PitchAnalysisResult:
        warnings = []

        notes = self.detector.detect(audio_path)
        beat_result = self.beat_tracker.track(audio_path)
        key_result = self.key_analyzer.analyze(audio_path)

        duration_sec = float(librosa.get_duration(path=audio_path))

        meta = MetaInfo(
            bpm=beat_result.bpm,
            bpm_confidence=beat_result.confidence,
            key=key_result.key,
            key_confidence=key_result.confidence,
            duration_sec=duration_sec,
        )

        return PitchAnalysisResult(
            version=self.VERSION,
            meta=meta,
            analysis_info={
                "quantize_mode": "disabled",
                "measure_segmentation": "disabled",
                "detector": "basic-pitch",
                "beat_backend": "librosa",
                "key_backend": "librosa_chroma",
            },
            raw_notes=notes,
            warnings=warnings,
        )
