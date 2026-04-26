import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from app.modules.pitch.config import PitchDetectionConfig
from app.modules.pitch.detector import PitchDetector
from app.modules.pitch.exceptions import AudioTooLongError, PitchModelUnavailableError
from app.modules.pitch.types import Note


class TestPitchDetector(unittest.TestCase):
    def test_default_backend_is_rmvpe(self):
        detector = PitchDetector()

        self.assertEqual(detector.backend_name, "rmvpe")
        self.assertEqual(PitchDetector._normalize_backend("unknown"), "rmvpe")

    def test_detect_filters_by_confidence_and_sorts(self):
        cfg = PitchDetectionConfig(confidence_threshold=0.5, pitch_backend="basic-pitch")
        detector = PitchDetector(cfg)

        audio_path = Path(__file__)

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

        with patch("app.modules.pitch.detector.get_audio_duration", return_value=1.2), patch(
            "app.modules.pitch.detector.midi_to_note", side_effect=["E4", "C4"]
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

        with patch("app.modules.pitch.detector.get_audio_duration", return_value=3.0):
            with self.assertRaises(AudioTooLongError):
                detector._validate_audio_length("dummy.wav")

    def test_detect_raises_when_basic_pitch_missing(self):
        cfg = PitchDetectionConfig(confidence_threshold=0.5, pitch_backend="basic-pitch")
        detector = PitchDetector(cfg)
        audio_path = Path(__file__)

        with patch("app.modules.pitch.detector.get_audio_duration", return_value=0.8), patch.dict(
            sys.modules,
            {
                "basic_pitch.inference": None,
                "basic_pitch.note_creation": None,
            },
            clear=False,
        ):
            with self.assertRaises(PitchModelUnavailableError):
                detector.detect(str(audio_path))

    def test_detect_with_rmvpe_segments_notes_from_f0_frames(self):
        cfg = PitchDetectionConfig(
            pitch_backend="rmvpe",
            confidence_threshold=0.5,
            rmvpe_sample_rate=16000,
            rmvpe_step_size_ms=10,
            crepe_vuv_confidence_threshold=0.45,
            crepe_max_unvoiced_gap_sec=0.02,
            crepe_pitch_jump_semitones=1.0,
            crepe_min_note_duration_sec=0.01,
            crepe_min_voiced_frames=1,
            crepe_smoothing_window=3,
        )
        detector = PitchDetector(cfg)
        audio_path = Path(__file__)

        midi_vals = np.array([60.0, 60.1, 0.0, 60.0, 60.2, 64.0, 64.1, 64.0], dtype=float)
        freqs = np.where(midi_vals > 0.0, 440.0 * (2.0 ** ((midi_vals - 69.0) / 12.0)), 0.0)

        class FakeRMVPE:
            def infer_from_audio(self, _audio, thred=0.03):
                self.threshold = thred
                return freqs

        fake_rmvpe = types.ModuleType("rmvpe")
        fake_rmvpe.RMVPE = FakeRMVPE

        with patch("app.modules.pitch.detector.get_audio_duration", return_value=1.0), patch.object(
            detector,
            "_load_audio_mono",
            return_value=(np.zeros(16000, dtype=np.float32), 16000),
        ), patch(
            "app.modules.pitch.detector.midi_to_note", side_effect=lambda midi: f"M{int(midi)}"
        ), patch.dict(
            sys.modules,
            {"rmvpe": fake_rmvpe},
            clear=False,
        ):
            notes = detector.detect(str(audio_path))

        self.assertEqual(len(notes), 2)
        self.assertEqual([n.pitch for n in notes], ["M60", "M64"])
        self.assertTrue(all(n.confidence >= 0.5 for n in notes))

    def test_detect_raises_when_rmvpe_missing(self):
        cfg = PitchDetectionConfig(pitch_backend="rmvpe")
        detector = PitchDetector(cfg)
        audio_path = Path(__file__)

        with patch("app.modules.pitch.detector.get_audio_duration", return_value=0.8), patch.object(
            detector,
            "_load_audio_mono",
            return_value=(np.zeros(16000, dtype=np.float32), 16000),
        ), patch(
            "app.modules.pitch.detector.importlib.import_module",
            side_effect=ImportError("rmvpe missing"),
        ):
            with self.assertRaises(PitchModelUnavailableError):
                detector.detect(str(audio_path))

    def test_detect_raises_when_rmvpe_model_path_missing(self):
        cfg = PitchDetectionConfig(pitch_backend="rmvpe", rmvpe_model_path="missing-rmvpe-model.pt")
        detector = PitchDetector(cfg)
        audio_path = Path(__file__)

        with patch("app.modules.pitch.detector.get_audio_duration", return_value=0.8):
            with self.assertRaises(PitchModelUnavailableError):
                detector.detect(str(audio_path))

    def test_rmvpe_falls_back_to_crepe_when_model_unavailable(self):
        cfg = PitchDetectionConfig(pitch_backend="rmvpe", pitch_backend_fallbacks=("crepe",))
        detector = PitchDetector(cfg)
        audio_path = Path(__file__)
        fallback_notes = [Note(pitch="C4", start_time=0.1, end_time=0.5, confidence=0.9)]

        with patch("app.modules.pitch.detector.get_audio_duration", return_value=0.8), patch.object(
            PitchDetector,
            "_detect_with_rmvpe",
            side_effect=PitchModelUnavailableError("rmvpe missing"),
        ), patch.object(
            PitchDetector,
            "_detect_with_crepe",
            return_value=fallback_notes,
        ):
            notes = detector.detect(str(audio_path))

        self.assertEqual(notes, fallback_notes)
        self.assertEqual(detector.active_backend_name, "crepe")
        self.assertEqual(detector.backend_warnings, ["pitch_backend_fallback:rmvpe->crepe"])

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

        audio_path = Path(__file__)

        fake_crepe = types.ModuleType("crepe")

        # Two note regions around C4 and E4 with a short unvoiced gap in the first note.
        times = np.array([0.00, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07], dtype=float)
        midi_vals = np.array([60.0, 60.1, 60.0, 60.0, 60.2, 64.0, 64.1, 64.0], dtype=float)
        freqs = 440.0 * (2.0 ** ((midi_vals - 69.0) / 12.0))
        confs = np.array([0.9, 0.91, 0.1, 0.92, 0.9, 0.93, 0.94, 0.93], dtype=float)

        fake_crepe.predict = lambda *args, **kwargs: (times, freqs, confs, None)

        with patch("app.modules.pitch.detector.get_audio_duration", return_value=1.0), patch.object(
            detector,
            "_load_audio_mono",
            return_value=(np.zeros(22050, dtype=np.float32), 22050),
        ), patch(
            "app.modules.pitch.detector.midi_to_note", side_effect=lambda midi: f"M{int(midi)}"
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
        audio_path = Path(__file__)

        with patch("app.modules.pitch.detector.get_audio_duration", return_value=0.8), patch.object(
            detector,
            "_load_audio_mono",
            return_value=(np.zeros(22050, dtype=np.float32), 22050),
        ), patch.object(
            detector,
            "_predict_with_torchcrepe",
            side_effect=RuntimeError("torchcrepe unavailable"),
        ), patch.dict(
            sys.modules,
            {"crepe": None},
            clear=False,
        ):
            with self.assertRaises(PitchModelUnavailableError):
                detector.detect(str(audio_path))

    def test_detect_with_crepe_uses_chunked_loading_for_long_audio(self):
        cfg = PitchDetectionConfig(
            pitch_backend="crepe",
            sample_rate=100,
            chunk_size_sec=1.0,
            confidence_threshold=0.0,
            crepe_vuv_confidence_threshold=0.0,
            crepe_step_size_ms=100,
            crepe_min_note_duration_sec=0.01,
            crepe_min_voiced_frames=1,
            crepe_smoothing_window=1,
        )
        detector = PitchDetector(cfg)

        fake_crepe = types.ModuleType("crepe")

        def _predict(audio, sr, **_kwargs):
            frame_count = max(1, int(np.ceil(float(audio.shape[0]) / max(1.0, sr * 0.1))))
            times = np.arange(frame_count, dtype=float) * 0.1
            freqs = np.full(frame_count, 440.0, dtype=float)
            confs = np.full(frame_count, 0.9, dtype=float)
            return times, freqs, confs, None

        fake_crepe.predict = _predict
        load_calls: list[tuple[float, float | None]] = []

        def _fake_load(_path, sample_rate, offset=0.0, duration=None):
            load_calls.append((float(offset), None if duration is None else float(duration)))
            samples = max(1, int(round(float((duration or 0.1)) * float(sample_rate))))
            return np.zeros(samples, dtype=np.float32), int(sample_rate)

        with patch.object(detector, "_load_audio_mono", side_effect=_fake_load), patch(
            "app.modules.pitch.detector.midi_to_note", return_value="A4"
        ), patch.dict(
            sys.modules,
            {"crepe": fake_crepe},
            clear=False,
        ):
            notes = detector._detect_with_crepe(Path("dummy.wav"), duration_sec=3.2)

        self.assertGreaterEqual(len(load_calls), 3)
        self.assertGreaterEqual(len(notes), 1)
        self.assertGreaterEqual(notes[0].start_time, 0.0)
        self.assertLessEqual(notes[-1].end_time, 3.2)

    def test_frames_to_notes_drops_unstable_pitch_segment(self):
        cfg = PitchDetectionConfig(
            confidence_threshold=0.5,
            crepe_vuv_confidence_threshold=0.0,
            crepe_min_note_duration_sec=0.01,
            crepe_min_voiced_frames=1,
            crepe_pitch_jump_semitones=10.0,
            crepe_smoothing_window=1,
        )
        detector = PitchDetector(cfg)

        times = np.array([0.00, 0.01, 0.02, 0.03], dtype=float)
        midi_vals = np.array([60.0, 63.6, 60.1, 63.5], dtype=float)
        freqs = 440.0 * (2.0 ** ((midi_vals - 69.0) / 12.0))
        confs = np.array([0.92, 0.93, 0.94, 0.95], dtype=float)

        notes = detector._frames_to_notes(
            times=times,
            frequencies=freqs,
            confidences=confs,
            duration_sec=1.0,
        )

        self.assertEqual(notes, [])


if __name__ == "__main__":
    unittest.main()
