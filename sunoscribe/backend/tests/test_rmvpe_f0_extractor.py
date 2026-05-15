import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from app.modules.pitch.config import PitchDetectionConfig
from app.modules.pitch.detector import PitchDetector
from app.modules.pitch.exceptions import PitchDetectionFailedError, PitchModelUnavailableError
from app.modules.pitch.f0_extractor import RMVPEF0Extractor


class TestRMVPEF0Extractor(unittest.TestCase):
    def test_extract_returns_authoritative_f0_track_without_note_segmentation(self):
        cfg = PitchDetectionConfig(
            pitch_backend="rmvpe",
            rmvpe_sample_rate=16000,
            rmvpe_step_size_ms=10,
            rmvpe_vuv_threshold=0.3,
        )
        detector = PitchDetector(cfg)
        extractor = RMVPEF0Extractor(config=cfg, detector=detector)
        audio_path = Path(__file__)
        times = np.array([0.00, 0.01, 0.02], dtype=float)
        frequencies = np.array([261.625565, 263.0, 0.0], dtype=float)
        confidences = np.array([0.92, 0.88, 0.05], dtype=float)

        with patch.object(detector, "_validate_audio_length", return_value=0.03), patch.object(
            detector,
            "_resolve_rmvpe_model_path",
            return_value=None,
        ), patch.object(detector, "_build_rmvpe_model", return_value=object()), patch.object(
            detector,
            "_load_audio_mono",
            return_value=(np.zeros(480, dtype=np.float32), 16000),
        ), patch.object(
            detector,
            "_predict_rmvpe_frames",
            return_value=(times, frequencies, confidences),
        ), patch.object(
            detector,
            "_frames_to_notes",
            side_effect=AssertionError("F0 extractor must not segment notes"),
        ):
            f0_track = extractor.extract(str(audio_path), source_stem="vocals")

        self.assertEqual(f0_track.backend, "rmvpe")
        self.assertEqual(f0_track.source_stem, "vocals")
        self.assertEqual(len(f0_track.frames), 3)
        self.assertEqual(f0_track.frames[0].time_sec, 0.0)
        self.assertTrue(f0_track.frames[0].voiced)
        self.assertFalse(f0_track.frames[2].voiced)
        self.assertEqual(f0_track.analysis_info["extractor"], RMVPEF0Extractor.VERSION)
        self.assertEqual(f0_track.analysis_info["stage"], "F0Track")
        self.assertTrue(f0_track.analysis_info["authoritative"])
        self.assertFalse(f0_track.analysis_info["fallback_allowed"])
        self.assertIsNotNone(extractor.last_extraction_artifacts)
        self.assertEqual(extractor.last_extraction_artifacts["backend"], "rmvpe")

    def test_extract_fails_explicitly_when_rmvpe_unavailable_without_fallback(self):
        cfg = PitchDetectionConfig(
            pitch_backend="rmvpe",
            pitch_backend_fallbacks=("crepe", "basic-pitch"),
            allow_backend_fallbacks=True,
        )
        detector = PitchDetector(cfg)
        extractor = RMVPEF0Extractor(config=cfg, detector=detector)

        with patch.object(detector, "_validate_audio_length", return_value=1.0), patch.object(
            detector,
            "_resolve_rmvpe_model_path",
            return_value=None,
        ), patch.object(
            detector,
            "_build_rmvpe_model",
            side_effect=PitchModelUnavailableError("rmvpe missing"),
        ), patch.object(detector, "_detect_with_crepe") as mocked_crepe, patch.object(
            detector,
            "_detect_with_basic_pitch",
        ) as mocked_basic_pitch:
            with self.assertRaises(PitchModelUnavailableError):
                extractor.extract(str(Path(__file__)), source_stem="vocals")

        mocked_crepe.assert_not_called()
        mocked_basic_pitch.assert_not_called()
        self.assertEqual(detector.config, cfg)
        self.assertEqual(detector.backend_name, "rmvpe")

    def test_extract_fails_explicitly_when_rmvpe_returns_no_frames(self):
        cfg = PitchDetectionConfig(pitch_backend="rmvpe")
        detector = PitchDetector(cfg)
        extractor = RMVPEF0Extractor(config=cfg, detector=detector)

        with patch.object(detector, "_validate_audio_length", return_value=1.0), patch.object(
            detector,
            "_resolve_rmvpe_model_path",
            return_value=None,
        ), patch.object(detector, "_build_rmvpe_model", return_value=object()), patch.object(
            detector,
            "_load_audio_mono",
            return_value=(np.zeros(16000, dtype=np.float32), 16000),
        ), patch.object(
            detector,
            "_predict_rmvpe_frames",
            return_value=(np.array([]), np.array([]), np.array([])),
        ):
            with self.assertRaisesRegex(PitchDetectionFailedError, "rmvpe_returned_no_frames"):
                extractor.extract(str(Path(__file__)), source_stem="vocals")

        self.assertIsNotNone(extractor.last_extraction_artifacts)
        self.assertEqual(extractor.last_extraction_artifacts["warnings"], ["rmvpe_returned_no_frames"])
        self.assertFalse(extractor.last_extraction_artifacts["fallback_allowed"])


if __name__ == "__main__":
    unittest.main()
