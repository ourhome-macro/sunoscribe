import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from app.modules.pitch.config import PitchDetectionConfig
from app.modules.pitch.detector import PitchDetector
from app.modules.pitch.exceptions import AudioTooLongError, PitchModelUnavailableError


class TestPitchDetector(unittest.TestCase):
    def test_detect_filters_by_confidence_and_sorts(self):
        cfg = PitchDetectionConfig(confidence_threshold=0.5)
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
        cfg = PitchDetectionConfig(max_audio_length_sec=1.0)
        detector = PitchDetector(cfg)

        with patch("app.modules.pitch.detector.librosa.get_duration", return_value=3.0):
            with self.assertRaises(AudioTooLongError):
                detector._validate_audio_length("dummy.wav")

    def test_detect_raises_when_basic_pitch_missing(self):
        cfg = PitchDetectionConfig(confidence_threshold=0.5)
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


if __name__ == "__main__":
    unittest.main()
