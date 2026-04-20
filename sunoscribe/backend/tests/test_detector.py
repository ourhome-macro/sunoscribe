import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from app.modules.pitch.config import PitchDetectionConfig
from app.modules.pitch.detector import PitchDetector
from app.modules.pitch.exceptions import AudioTooLongError, PitchModelUnavailableError


class TestPitchDetector(unittest.TestCase):
    def test_detect_filters_by_confidence_and_sorts(self):
        cfg = PitchDetectionConfig(confidence_threshold=0.5, pitch_backend="basic-pitch")
        detector = PitchDetector(cfg)

        with tempfile.TemporaryDirectory() as td:
            audio_path = Path(td) / "dummy.wav"
            audio_path.write_bytes(b"fake")

            fake_inference = types.ModuleType("basic_pitch.inference")
            fake_creation = types.ModuleType("basic_pitch.note_creation")

            def _predict(_):
                # start, end, midi, conf
                return {}, None, [
                    (0.8, 1.0, 64, 0.9),
                    (0.1, 0.3, 60, 0.7),
                    (0.5, 0.7, 62, 0.2),  # filtered by confidence
                ]

            fake_inference.predict = _predict
            fake_creation.model_output_to_notes = lambda **kwargs: []

            with patch("app.modules.pitch.detector.librosa.get_duration", return_value=1.2), patch(
                "app.modules.pitch.detector.librosa.midi_to_note", side_effect=["E4", "C4"]
            ), patch.dict(
                sys.modules,
                {
                    "basic_pitch": types.ModuleType("basic_pitch"),
                    "basic_pitch.inference": fake_inference,
                    "basic_pitch.note_creation": fake_creation,
                },
                clear=False,
            ):
                notes = detector.detect(str(audio_path))

        self.assertEqual(len(notes), 2)
        self.assertEqual([n.pitch for n in notes], ["C4", "E4"])
        self.assertLessEqual(notes[0].start_time, notes[1].start_time)

    def test_validate_audio_length_raises(self):
        cfg = PitchDetectionConfig(max_audio_length_sec=1.0, pitch_backend="basic-pitch")
        detector = PitchDetector(cfg)

        with patch("app.modules.pitch.detector.librosa.get_duration", return_value=3.0):
            with self.assertRaises(AudioTooLongError):
                detector._validate_audio_length("dummy.wav")

    def test_detect_raises_when_basic_pitch_missing(self):
        cfg = PitchDetectionConfig(confidence_threshold=0.5, pitch_backend="basic-pitch")
        detector = PitchDetector(cfg)

        with tempfile.TemporaryDirectory() as td:
            audio_path = Path(td) / "dummy.wav"
            audio_path.write_bytes(b"fake")

            with patch("app.modules.pitch.detector.librosa.get_duration", return_value=0.8), patch.dict(
                sys.modules,
                {
                    "basic_pitch.inference": None,
                    "basic_pitch.note_creation": None,
                },
                clear=False,
            ):
                with self.assertRaises(PitchModelUnavailableError):
                    detector.detect(str(audio_path))

    def test_detect_with_crepe_segments_notes_and_bridges_short_unvoiced_gap(self):
        cfg = PitchDetectionConfig(
            pitch_backend="crepe",
            confidence_threshold=0.5,
            crepe_vuv_confidence_threshold=0.45,
            crepe_step_size_ms=10,
            crepe_max_unvoiced_gap_sec=0.02,
            crepe_pitch_jump_semitones=1.0,
            crepe_min_note_duration_sec=0.01,
            crepe_min_voiced_frames=1,
            crepe_smoothing_window=3,
        )
        detector = PitchDetector(cfg)

        with tempfile.TemporaryDirectory() as td:
            audio_path = Path(td) / "dummy.wav"
            audio_path.write_bytes(b"fake")

            fake_crepe = types.ModuleType("crepe")

            # Two note regions around C4 and E4 with a short unvoiced gap in the first note.
            times = np.array([0.00, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07], dtype=float)
            midi_vals = np.array([60.0, 60.1, 60.0, 60.0, 60.2, 64.0, 64.1, 64.0], dtype=float)
            freqs = 440.0 * (2.0 ** ((midi_vals - 69.0) / 12.0))
            confs = np.array([0.9, 0.91, 0.1, 0.92, 0.9, 0.93, 0.94, 0.93], dtype=float)

            fake_crepe.predict = lambda *args, **kwargs: (times, freqs, confs, None)

            with patch("app.modules.pitch.detector.librosa.get_duration", return_value=1.0), patch(
                "app.modules.pitch.detector.librosa.load", return_value=(np.zeros(22050, dtype=np.float32), 22050)
            ), patch(
                "app.modules.pitch.detector.librosa.midi_to_note", side_effect=lambda midi: f"M{int(midi)}"
            ), patch.dict(
                sys.modules,
                {"crepe": fake_crepe},
                clear=False,
            ):
                notes = detector.detect(str(audio_path))

        self.assertEqual(len(notes), 2)
        self.assertEqual([n.pitch for n in notes], ["M60", "M64"])
        self.assertLess(notes[0].end_time, notes[1].start_time)

    def test_detect_raises_when_crepe_missing(self):
        cfg = PitchDetectionConfig(pitch_backend="crepe")
        detector = PitchDetector(cfg)

        with tempfile.TemporaryDirectory() as td:
            audio_path = Path(td) / "dummy.wav"
            audio_path.write_bytes(b"fake")

            with patch("app.modules.pitch.detector.librosa.get_duration", return_value=0.8), patch.dict(
                sys.modules,
                {"crepe": None},
                clear=False,
            ):
                with self.assertRaises(PitchModelUnavailableError):
                    detector.detect(str(audio_path))


if __name__ == "__main__":
    unittest.main()
