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


if __name__ == "__main__":
    unittest.main()
