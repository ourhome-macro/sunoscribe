import unittest
from unittest.mock import patch

import numpy as np

from app.modules.pitch.config import PitchDetectionConfig
from app.modules.pitch.beat_tracker import BeatTracker
from app.modules.pitch.exceptions import NoBeatsDetectedError


class TestBeatTracker(unittest.TestCase):
    def test_track_returns_bpm_and_beats(self):
        tracker = BeatTracker()

        with patch("librosa.load", return_value=(np.array([0.1, 0.2, 0.1]), 22050)), patch(
            "librosa.beat.beat_track", return_value=(120.0, np.array([0, 10, 20]))
        ), patch("librosa.frames_to_time", return_value=np.array([0.0, 0.5, 1.0])), patch(
            "librosa.onset.onset_strength", return_value=np.array([1.0, 1.2, 0.9] * 10)
        ):
            result = tracker.track("dummy.wav")

        self.assertAlmostEqual(result.bpm, 120.0, places=3)
        self.assertEqual(result.beat_times, [0.0, 0.5, 1.0])
        self.assertGreaterEqual(result.confidence, 0.0)
        self.assertLessEqual(result.confidence, 1.0)

    def test_track_raises_for_empty_audio(self):
        tracker = BeatTracker()

        with patch("librosa.load", return_value=(np.array([]), 22050)):
            with self.assertRaises(NoBeatsDetectedError):
                tracker.track("dummy.wav")

    def test_track_refines_bpm_from_beat_intervals(self):
        tracker = BeatTracker()

        beat_times = np.array(
            [
                0.0,
                60.0 / 115.0,
                2.0 * 60.0 / 115.0,
                3.0 * 60.0 / 115.0,
            ]
        )

        with patch("librosa.load", return_value=(np.array([0.1, 0.2, 0.1, 0.2]), 22050)), patch(
            "librosa.beat.beat_track", return_value=(117.4, np.array([0, 1, 2, 3]))
        ), patch("librosa.frames_to_time", return_value=beat_times), patch(
            "librosa.onset.onset_strength", return_value=np.array([1.0, 1.1, 0.95, 1.05, 1.0, 1.1])
        ):
            result = tracker.track("dummy.wav")

        self.assertLess(result.bpm, 117.4)
        self.assertAlmostEqual(result.bpm, 115.48, places=2)

    def test_track_refine_weights_are_configurable(self):
        cfg = PitchDetectionConfig(
            bpm_refine_enabled=True,
            bpm_refine_ioi_weight=1.0,
            bpm_refine_raw_weight=0.0,
        )
        tracker = BeatTracker(cfg)

        beat_times = np.array(
            [
                0.0,
                60.0 / 115.0,
                2.0 * 60.0 / 115.0,
                3.0 * 60.0 / 115.0,
            ]
        )

        with patch("librosa.load", return_value=(np.array([0.1, 0.2, 0.1, 0.2]), 22050)), patch(
            "librosa.beat.beat_track", return_value=(117.4, np.array([0, 1, 2, 3]))
        ), patch("librosa.frames_to_time", return_value=beat_times), patch(
            "librosa.onset.onset_strength", return_value=np.array([1.0, 1.1, 0.95, 1.05, 1.0, 1.1])
        ):
            result = tracker.track("dummy.wav")

        self.assertAlmostEqual(result.bpm, 115.0, places=2)


if __name__ == "__main__":
    unittest.main()
