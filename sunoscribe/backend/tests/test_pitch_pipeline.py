import unittest
from unittest.mock import patch

from app.modules.pitch.pipeline import PitchPipeline
from app.modules.pitch.types import Note


class TestPitchPipeline(unittest.TestCase):
    def test_run_with_mocks(self):
        pipeline = PitchPipeline()

        mock_notes = [
            Note(pitch="C4", start_time=0.1, end_time=0.6, confidence=0.91),
            Note(pitch="E4", start_time=0.7, end_time=1.2, confidence=0.88),
        ]

        class _BeatResult:
            bpm = 120.0
            beat_times = [0.0, 0.5, 1.0]
            confidence = 0.93

        class _KeyResult:
            key = "C Major"
            confidence = 0.89

        with patch.object(pipeline.detector, "detect", return_value=mock_notes), patch.object(
            pipeline.beat_tracker, "track", return_value=_BeatResult()
        ), patch.object(pipeline.key_analyzer, "analyze", return_value=_KeyResult()), patch(
            "app.modules.pitch.pipeline.librosa.get_duration", return_value=12.34
        ):
            result = pipeline.run("dummy.wav")

        self.assertEqual(result.version, "1.0")
        self.assertEqual(result.meta.bpm, 120.0)
        self.assertEqual(result.meta.key, "C Major")
        self.assertEqual(result.meta.duration_sec, 12.34)
        self.assertEqual(len(result.raw_notes), 2)
        self.assertEqual(result.raw_notes[0].pitch, "C4")
        self.assertEqual(result.analysis_info["quantize_mode"], "disabled")
        self.assertEqual(result.analysis_info["measure_segmentation"], "disabled")


if __name__ == "__main__":
    unittest.main()
