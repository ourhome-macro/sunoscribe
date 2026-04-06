import unittest

from app.modules.pitch.config import PitchDetectionConfig
from app.modules.pitch.quantizer import NoteQuantizer
from app.modules.pitch.types import Note, NoteType


class TestNoteQuantizer(unittest.TestCase):
    def test_quantize_assigns_note_type_and_measure(self):
        cfg = PitchDetectionConfig(quantize_mode="adaptive", quantize_precision=0.25)
        quantizer = NoteQuantizer(cfg)

        notes = [
            Note(pitch="C4", start_time=0.0, end_time=0.5, confidence=0.9),
            Note(pitch="E4", start_time=2.0, end_time=2.5, confidence=0.8),
        ]
        quantized = quantizer.quantize(notes, bpm=120.0, beat_times=[0.0, 0.5, 1.0, 1.5])

        self.assertEqual(len(quantized), 2)
        self.assertEqual(quantized[0].duration_beats, 1.0)
        self.assertEqual(quantized[0].note_type, NoteType.QUARTER)
        self.assertEqual(quantized[0].measure_num, 1)
        self.assertEqual(quantized[1].measure_num, 2)

    def test_quantize_with_invalid_bpm_returns_empty(self):
        cfg = PitchDetectionConfig()
        quantizer = NoteQuantizer(cfg)
        notes = [Note(pitch="C4", start_time=0.0, end_time=0.5, confidence=0.9)]

        quantized = quantizer.quantize(notes, bpm=0.0, beat_times=[])
        self.assertEqual(quantized, [])


if __name__ == "__main__":
    unittest.main()
