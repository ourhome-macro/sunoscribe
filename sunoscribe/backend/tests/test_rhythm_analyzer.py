import unittest

from app.modules.pitch.rhythm_analyzer import RhythmAnalyzer


class TestRhythmAnalyzer(unittest.TestCase):
    def test_stable_rhythm(self):
        analyzer = RhythmAnalyzer()
        result = analyzer.analyze([0.0, 0.5, 1.0, 1.5, 2.0])

        self.assertEqual(result.rhythm_type, "stable")
        self.assertGreaterEqual(result.stability_score, 0.95)

    def test_free_when_beats_insufficient(self):
        analyzer = RhythmAnalyzer()
        result = analyzer.analyze([0.0, 0.5])

        self.assertEqual(result.rhythm_type, "free")
        self.assertEqual(result.stability_score, 0.0)


if __name__ == "__main__":
    unittest.main()
