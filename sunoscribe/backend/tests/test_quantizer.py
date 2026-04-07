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

    def test_measure_location_uses_configured_beats_per_bar(self):
        cfg = PitchDetectionConfig(beats_per_bar=3, quantize_precision=0.25)
        quantizer = NoteQuantizer(cfg)

        notes = [
            Note(pitch="C4", start_time=0.0, end_time=0.5, confidence=0.9),
            Note(pitch="D4", start_time=1.6, end_time=2.1, confidence=0.9),
        ]
        quantized = quantizer.quantize(notes, bpm=120.0, beat_times=[0.0, 0.5, 1.0, 1.5, 2.0])

        self.assertEqual(quantized[0].measure_num, 1)
        self.assertEqual(quantized[1].measure_num, 2)

    def test_filters_very_short_notes_by_min_duration(self):
        cfg = PitchDetectionConfig(quantize_min_duration_beats=0.25, quantize_precision=0.125)
        quantizer = NoteQuantizer(cfg)

        notes = [
            Note(pitch="C4", start_time=0.0, end_time=0.06, confidence=0.9),  # 0.12 beat @ 120 BPM
            Note(pitch="D4", start_time=0.1, end_time=0.35, confidence=0.9),  # 0.5 beat
        ]
        quantized = quantizer.quantize(notes, bpm=120.0, beat_times=[0.0, 0.5, 1.0])

        self.assertEqual(len(quantized), 1)
        self.assertEqual(quantized[0].pitch, "D4")

    def test_adaptive_tolerance_for_triplet_and_dotted(self):
        cfg = PitchDetectionConfig(
            quantize_mode="adaptive",
            quantize_precision=0.01,
            adaptive_triplet_tolerance_beats=0.08,
            adaptive_dotted_tolerance_beats=0.12,
        )
        quantizer = NoteQuantizer(cfg)

        notes = [
            Note(pitch="C4", start_time=0.0, end_time=0.71, confidence=0.9),   # ≈1.42 beats -> dotted quarter window
            Note(pitch="E4", start_time=0.8, end_time=1.13, confidence=0.9),  # ≈0.66 beats -> triplet window
        ]
        quantized = quantizer.quantize(notes, bpm=120.0, beat_times=[0.0, 0.5, 1.0, 1.5])

        self.assertEqual(len(quantized), 2)
        self.assertEqual(quantized[0].note_type, NoteType.DOTTED_QUARTER)
        self.assertEqual(quantized[1].note_type, NoteType.TRIPLET)

    def test_filters_low_confidence_noise_notes(self):
        cfg = PitchDetectionConfig(
            quantize_noise_confidence_floor=0.6,
            quantize_min_duration_beats=0.125,
        )
        quantizer = NoteQuantizer(cfg)

        notes = [
            Note(pitch="C4", start_time=0.0, end_time=0.5, confidence=0.55),
            Note(pitch="D4", start_time=0.6, end_time=1.1, confidence=0.85),
        ]
        quantized = quantizer.quantize(notes, bpm=120.0, beat_times=[0.0, 0.5, 1.0])

        self.assertEqual(len(quantized), 1)
        self.assertEqual(quantized[0].pitch, "D4")

    def test_merges_adjacent_same_pitch_notes(self):
        cfg = PitchDetectionConfig(
            quantize_merge_same_pitch_enabled=True,
            quantize_merge_same_pitch_gap_sec=0.08,
            quantize_merge_min_confidence=0.5,
            quantize_precision=0.125,
        )
        quantizer = NoteQuantizer(cfg)

        notes = [
            Note(pitch="A4", start_time=0.0, end_time=0.4, confidence=0.9),
            Note(pitch="A4", start_time=0.44, end_time=0.9, confidence=0.88),
            Note(pitch="G4", start_time=1.0, end_time=1.4, confidence=0.9),
        ]
        quantized = quantizer.quantize(notes, bpm=120.0, beat_times=[0.0, 0.5, 1.0, 1.5])

        self.assertEqual(len(quantized), 2)
        self.assertEqual(quantized[0].pitch, "A4")
        self.assertAlmostEqual(quantized[0].start_time, 0.0, places=3)
        self.assertAlmostEqual(quantized[0].end_time, 0.9, places=3)

    def test_resolves_overlapped_notes(self):
        cfg = PitchDetectionConfig(
            quantize_overlap_resolution_enabled=True,
            quantize_overlap_min_gap_sec=0.01,
            quantize_merge_same_pitch_enabled=False,
        )
        quantizer = NoteQuantizer(cfg)

        notes = [
            Note(pitch="C4", start_time=0.0, end_time=0.6, confidence=0.95),
            Note(pitch="E4", start_time=0.4, end_time=0.9, confidence=0.6),
        ]
        quantized = quantizer.quantize(notes, bpm=120.0, beat_times=[0.0, 0.5, 1.0])

        self.assertEqual(len(quantized), 2)
        self.assertLessEqual(quantized[0].end_time, quantized[1].start_time)

    def test_optional_near_pitch_merge(self):
        cfg = PitchDetectionConfig(
            quantize_merge_same_pitch_enabled=True,
            quantize_merge_near_pitch_enabled=True,
            quantize_merge_near_pitch_max_semitone=1,
            quantize_merge_same_pitch_gap_sec=0.06,
        )
        quantizer = NoteQuantizer(cfg)

        notes = [
            Note(pitch="C4", start_time=0.0, end_time=0.3, confidence=0.9),
            Note(pitch="C#4", start_time=0.34, end_time=0.7, confidence=0.88),
        ]
        quantized = quantizer.quantize(notes, bpm=120.0, beat_times=[0.0, 0.5, 1.0])

        self.assertEqual(len(quantized), 1)
        self.assertEqual(quantized[0].pitch, "C4")
        self.assertAlmostEqual(quantized[0].end_time, 0.7, places=3)


if __name__ == "__main__":
    unittest.main()
