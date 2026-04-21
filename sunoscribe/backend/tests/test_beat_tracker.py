import sys
import types
import unittest
from unittest.mock import patch

import numpy as np

from app.modules.pitch.beat_tracker import BeatTracker
from app.modules.pitch.config import PitchDetectionConfig
from app.modules.pitch.exceptions import NoBeatsDetectedError


def _fake_librosa_module(
    *,
    y: np.ndarray,
    sr: int,
    tempo: float,
    beat_frames: np.ndarray,
    beat_times: np.ndarray,
    onset_env: np.ndarray,
):
    module = types.ModuleType("librosa")
    module.load = lambda *_args, **_kwargs: (y, sr)
    module.frames_to_time = lambda *_args, **_kwargs: beat_times
    module.beat = types.SimpleNamespace(beat_track=lambda **_kwargs: (tempo, beat_frames))
    module.onset = types.SimpleNamespace(onset_strength=lambda **_kwargs: onset_env)
    return module


class TestBeatTracker(unittest.TestCase):
    def test_track_returns_bpm_and_details(self):
        tracker = BeatTracker()

        fake_librosa = _fake_librosa_module(
            y=np.array([0.1, 0.2, 0.1, 0.2], dtype=float),
            sr=22050,
            tempo=120.0,
            beat_frames=np.array([0, 10, 20]),
            beat_times=np.array([0.0, 0.5, 1.0]),
            onset_env=np.array([1.0, 1.2, 0.9] * 10),
        )

        with patch.dict(sys.modules, {"librosa": fake_librosa}, clear=False):
            result = tracker.track("dummy.wav")

        self.assertAlmostEqual(result.bpm, 120.0, places=3)
        self.assertEqual(result.beat_times, [0.0, 0.5, 1.0])
        self.assertAlmostEqual(float(result.raw_bpm or 0.0), 120.0, places=3)
        self.assertGreaterEqual(result.confidence, 0.0)
        self.assertLessEqual(result.confidence, 1.0)

    def test_track_raises_for_empty_audio(self):
        tracker = BeatTracker()

        fake_librosa = _fake_librosa_module(
            y=np.array([], dtype=float),
            sr=22050,
            tempo=120.0,
            beat_frames=np.array([0]),
            beat_times=np.array([0.0]),
            onset_env=np.array([1.0]),
        )

        with patch.dict(sys.modules, {"librosa": fake_librosa}, clear=False):
            with self.assertRaises(NoBeatsDetectedError):
                tracker.track("dummy.wav")

    def test_refine_uses_candidates_and_dynamic_weight_for_stable_long_beats(self):
        tracker = BeatTracker()
        beats = [i * (60.0 / 115.0) for i in range(24)]
        decision = tracker._refine_bpm_from_beats(
            raw_bpm=117.4,
            beat_times=beats,
            audio_duration_sec=beats[-1] + 0.1,
        )

        self.assertTrue(decision.used_refine)
        self.assertIsNotNone(decision.ioi_bpm)
        self.assertIn(57.5, decision.candidate_bpms)
        self.assertIn(115.0, decision.candidate_bpms)
        self.assertAlmostEqual(float(decision.ioi_bpm), 115.0, places=3)
        self.assertAlmostEqual(decision.final_bpm, 115.36, places=2)
        self.assertGreater(decision.stability, 0.9)

    def test_refine_falls_back_to_raw_for_short_sequence(self):
        tracker = BeatTracker()
        decision = tracker._refine_bpm_from_beats(
            raw_bpm=117.4,
            beat_times=[0.0, 0.31, 0.62],
            audio_duration_sec=3.0,
        )

        self.assertFalse(decision.used_refine)
        self.assertAlmostEqual(decision.final_bpm, 117.4, places=3)

    def test_refine_weights_are_configurable(self):
        cfg = PitchDetectionConfig(
            bpm_refine_enabled=True,
            bpm_refine_ioi_weight=1.0,
            bpm_refine_raw_weight=0.0,
        )
        tracker = BeatTracker(cfg)
        beats = [0.0, 60.0 / 115.0, 2.0 * 60.0 / 115.0, 3.0 * 60.0 / 115.0]

        decision = tracker._refine_bpm_from_beats(
            raw_bpm=117.4,
            beat_times=beats,
            audio_duration_sec=2.2,
        )

        self.assertAlmostEqual(decision.final_bpm, 115.0, places=2)


if __name__ == "__main__":
    unittest.main()
