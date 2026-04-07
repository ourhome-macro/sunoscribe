from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import PitchDetectionConfig
from .exceptions import KeyAnalysisLowConfidenceError


@dataclass
class KeyAnalysisResult:
    key: str
    confidence: float
    method: str = "librosa"


class KeyAnalyzer:
    """使用 chroma + Krumhansl-Schmuckler 模板进行调式分析。"""

    NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

    MAJOR_TEMPLATE = np.array(
        [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88],
        dtype=np.float32,
    )
    MINOR_TEMPLATE = np.array(
        [6.33, 2.68, 3.52, 5.38, 2.6, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17],
        dtype=np.float32,
    )

    def __init__(self, config: PitchDetectionConfig | None = None) -> None:
        self.config = config or PitchDetectionConfig()

    @staticmethod
    def _corr(a: np.ndarray, b: np.ndarray) -> float:
        if np.allclose(a.std(), 0) or np.allclose(b.std(), 0):
            return 0.0
        return float(np.corrcoef(a, b)[0, 1])

    def _analyze_librosa(self, audio_path: str, method: str = "librosa") -> KeyAnalysisResult:
        import librosa

        y, sr = librosa.load(audio_path, sr=self.config.sample_rate, mono=True)
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
        chroma_sum = np.sum(chroma, axis=1)

        best_key = "C Major"
        best_score = -1.0
        second_score = -1.0

        for i in range(12):
            major_score = self._corr(chroma_sum, np.roll(self.MAJOR_TEMPLATE, i))
            minor_score = self._corr(chroma_sum, np.roll(self.MINOR_TEMPLATE, i))

            if major_score > best_score:
                second_score = best_score
                best_score = major_score
                best_key = f"{self.NOTE_NAMES[i]} Major"
            elif major_score > second_score:
                second_score = major_score

            if minor_score > best_score:
                second_score = best_score
                best_score = minor_score
                best_key = f"{self.NOTE_NAMES[i]} Minor"
            elif minor_score > second_score:
                second_score = minor_score

        raw_gap = max(0.0, best_score - max(second_score, -1.0))
        confidence = max(0.0, min(1.0, (best_score + 1.0) / 2.0 * 0.7 + raw_gap * 0.3))

        if confidence < self.config.key_min_confidence:
            raise KeyAnalysisLowConfidenceError(
                f"调式分析置信度过低: {confidence:.3f} < {self.config.key_min_confidence:.3f}"
            )

        return KeyAnalysisResult(key=best_key, confidence=confidence, method=method)

    def _analyze_music21(self, audio_path: str) -> KeyAnalysisResult:
        import importlib

        import librosa

        m21note = importlib.import_module("music21.note")
        m21stream = importlib.import_module("music21.stream")

        y, sr = librosa.load(audio_path, sr=self.config.sample_rate, mono=True)
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
        chroma_sum = np.sum(chroma, axis=1)

        s = m21stream.Stream()
        for i, weight in enumerate(chroma_sum):
            repeats = max(1, int(round(float(weight) * 5)))
            pitch_name = self.NOTE_NAMES[i]
            for _ in range(repeats):
                s.append(m21note.Note(f"{pitch_name}4", quarterLength=0.25))

        k = s.analyze("key")
        tonic = getattr(getattr(k, "tonic", None), "name", "C")
        mode = str(getattr(k, "mode", "major")).capitalize()
        corr = float(getattr(k, "correlationCoefficient", 0.75) or 0.75)
        confidence = max(0.0, min(1.0, corr))

        if confidence < self.config.key_min_confidence:
            raise KeyAnalysisLowConfidenceError(
                f"调式分析置信度过低: {confidence:.3f} < {self.config.key_min_confidence:.3f}"
            )

        return KeyAnalysisResult(key=f"{tonic} {mode}", confidence=confidence, method="music21")

    def analyze(self, audio_path: str) -> KeyAnalysisResult:
        backend = (self.config.key_backend or "librosa").lower()

        if backend == "music21":
            try:
                return self._analyze_music21(audio_path)
            except Exception:
                if not self.config.key_enable_music21_fallback:
                    raise
                return self._analyze_librosa(audio_path, method="librosa_fallback")

        if backend == "auto":
            try:
                return self._analyze_music21(audio_path)
            except Exception:
                return self._analyze_librosa(audio_path, method="librosa_auto_fallback")

        return self._analyze_librosa(audio_path, method="librosa")
