import unittest
from unittest.mock import patch

import numpy as np

from app.modules.pitch.config import PitchDetectionConfig
from app.modules.pitch.exceptions import KeyAnalysisLowConfidenceError
from app.modules.pitch.key_analyzer import KeyAnalyzer


class TestKeyAnalyzer(unittest.TestCase):
    def test_analyze_returns_key_and_confidence(self):
        analyzer = KeyAnalyzer(PitchDetectionConfig(key_min_confidence=0.05))

        fake_chroma = np.ones((12, 6), dtype=np.float32)
        with patch("librosa.load", return_value=(np.zeros(100), 22050)), patch(
            "librosa.feature.chroma_cqt", return_value=fake_chroma
        ):
            result = analyzer.analyze("dummy.wav")

        self.assertIn(" ", result.key)
        self.assertGreaterEqual(result.confidence, 0.0)
        self.assertLessEqual(result.confidence, 1.0)

    def test_analyze_raises_low_confidence(self):
        analyzer = KeyAnalyzer(PitchDetectionConfig(key_min_confidence=0.95))
        fake_chroma = np.zeros((12, 6), dtype=np.float32)

        with patch("librosa.load", return_value=(np.zeros(100), 22050)), patch(
            "librosa.feature.chroma_cqt", return_value=fake_chroma
        ):
            with self.assertRaises(KeyAnalysisLowConfidenceError):
                analyzer.analyze("dummy.wav")

    def test_auto_backend_fallbacks_to_librosa(self):
        analyzer = KeyAnalyzer(PitchDetectionConfig(key_backend="auto", key_min_confidence=0.05))

        with patch.object(analyzer, "_analyze_music21", side_effect=RuntimeError("music21 unavailable")), patch.object(
            analyzer,
            "_analyze_librosa",
            return_value=type("R", (), {"key": "C Major", "confidence": 0.8, "method": "librosa_auto_fallback"})(),
        ):
            result = analyzer.analyze("dummy.wav")

        self.assertEqual(result.method, "librosa_auto_fallback")

    def test_music21_backend_without_fallback_raises(self):
        analyzer = KeyAnalyzer(
            PitchDetectionConfig(key_backend="music21", key_enable_music21_fallback=False, key_min_confidence=0.05)
        )

        with patch.object(analyzer, "_analyze_music21", side_effect=RuntimeError("music21 unavailable")):
            with self.assertRaises(RuntimeError):
                analyzer.analyze("dummy.wav")


if __name__ == "__main__":
    unittest.main()
