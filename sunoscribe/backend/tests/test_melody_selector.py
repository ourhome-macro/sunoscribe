import unittest

from app.modules.pitch.config import PitchDetectionConfig
from app.modules.pitch.melody_selector import MelodySelector
from app.modules.pitch.types import Note


class TestMelodySelector(unittest.TestCase):
    def test_filters_low_confidence_short_and_out_of_range_notes(self):
        selector = MelodySelector(PitchDetectionConfig())
        notes = [
            Note(pitch="C2", start_time=0.0, end_time=0.4, confidence=0.9),
            Note(pitch="C4", start_time=0.5, end_time=0.58, confidence=0.9),
            Note(pitch="D4", start_time=0.7, end_time=1.1, confidence=0.4),
            Note(pitch="E4", start_time=1.2, end_time=1.6, confidence=0.88),
        ]

        result = selector.select(notes)

        self.assertEqual(result.detected_count, 4)
        self.assertEqual(result.kept_count, 1)
        self.assertEqual(result.notes[0].pitch, "E4")
        self.assertEqual(result.removed_pitch_range, 1)
        self.assertEqual(result.removed_short, 1)
        self.assertEqual(result.removed_low_confidence, 1)

    def test_merges_adjacent_near_pitch_fragments(self):
        selector = MelodySelector(
            PitchDetectionConfig(
                melody_merge_gap_sec=0.08,
                melody_merge_pitch_tolerance_semitones=1,
            )
        )
        notes = [
            Note(pitch="A4", start_time=0.0, end_time=0.30, confidence=0.85),
            Note(pitch="A#4", start_time=0.34, end_time=0.62, confidence=0.82),
        ]

        result = selector.select(notes)

        self.assertEqual(result.kept_count, 1)
        self.assertAlmostEqual(result.notes[0].start_time, 0.0, places=3)
        self.assertAlmostEqual(result.notes[0].end_time, 0.62, places=3)
        self.assertGreaterEqual(result.merged_count, 1)

    def test_removes_isolated_big_leap_spike(self):
        selector = MelodySelector(
            PitchDetectionConfig(
                melody_min_confidence=0.5,
                melody_short_note_min_confidence=0.5,
                melody_large_jump_semitones=12,
                melody_isolated_note_max_duration_sec=0.25,
                melody_isolated_note_min_confidence=0.62,
            )
        )
        notes = [
            Note(pitch="C4", start_time=0.0, end_time=0.35, confidence=0.9),
            Note(pitch="C6", start_time=0.40, end_time=0.52, confidence=0.58),
            Note(pitch="D4", start_time=0.60, end_time=0.95, confidence=0.9),
        ]

        result = selector.select(notes)

        self.assertEqual(result.kept_count, 2)
        self.assertEqual([n.pitch for n in result.notes], ["C4", "D4"])
        self.assertEqual(result.removed_big_leap, 1)


if __name__ == "__main__":
    unittest.main()
