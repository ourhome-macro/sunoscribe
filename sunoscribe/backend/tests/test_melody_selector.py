import unittest

from app.modules.pitch.config import PitchDetectionConfig
from app.modules.pitch.melody_selector import MelodySelector
from app.modules.pitch.reason_codes import OCTAVE_JUMP_CORRECTED, SHORT_GAP_BRIDGED, SHORT_NOTE_ABSORBED
from app.modules.pitch.types import Note


class TestMelodySelector(unittest.TestCase):
    def test_postprocessor_defaults_are_conservative(self):
        selector = MelodySelector(PitchDetectionConfig())

        self.assertFalse(selector.postprocessor.config.remove_isolated_fragments_enabled)
        self.assertTrue(selector.postprocessor.config.sustain_short_gaps_enabled)

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


    def test_bridge_short_gap_records_reason_code(self):
        selector = MelodySelector(
            PitchDetectionConfig(
                melody_min_confidence=0.5,
                melody_merge_gap_sec=0.08,
                melody_merge_pitch_tolerance_semitones=0,
            )
        )
        notes = [
            Note(pitch="C4", start_time=0.00, end_time=0.30, confidence=0.90),
            Note(pitch="C4", start_time=0.35, end_time=0.70, confidence=0.88),
        ]

        result = selector.select(notes)

        self.assertEqual(result.kept_count, 1)
        self.assertIn(SHORT_GAP_BRIDGED, result.notes[0].reason_codes)
        self.assertEqual(result.merged_count, 1)


    def test_retains_high_confidence_bridge_short_note_to_avoid_big_gap(self):
        selector = MelodySelector(
            PitchDetectionConfig(
                melody_min_confidence=0.5,
                melody_min_duration_sec=0.12,
                melody_short_note_min_confidence=0.5,
                melody_bridge_note_retention_enabled=True,
                melody_bridge_note_gap_threshold_sec=0.5,
                melody_bridge_note_small_gap_sec=0.05,
            )
        )
        notes = [
            Note(pitch="A3", start_time=0.00, end_time=0.30, confidence=0.90),
            Note(pitch="C4", start_time=0.48, end_time=0.59, confidence=0.82),
            Note(pitch="E4", start_time=0.86, end_time=1.16, confidence=0.88),
        ]

        result = selector.select(notes)

        self.assertEqual(result.kept_count, 3)
        self.assertIn(SHORT_GAP_BRIDGED, result.notes[1].reason_codes)
        self.assertEqual(result.postprocess_action_counts["bridge_note_retention"], 1)

    def test_absorbs_short_note_between_same_pitch_phrase(self):
        selector = MelodySelector(
            PitchDetectionConfig(
                melody_min_confidence=0.5,
                melody_short_note_min_confidence=0.5,
                melody_merge_gap_sec=0.08,
                melody_merge_pitch_tolerance_semitones=1,
            )
        )
        notes = [
            Note(pitch="C4", start_time=0.00, end_time=0.30, confidence=0.92),
            Note(pitch="D4", start_time=0.33, end_time=0.40, confidence=0.56),
            Note(pitch="C4", start_time=0.43, end_time=0.78, confidence=0.90),
        ]

        result = selector.select(notes)

        self.assertEqual(result.kept_count, 1)
        self.assertEqual(result.notes[0].pitch, "C4")
        self.assertAlmostEqual(result.notes[0].start_time, 0.00, places=3)
        self.assertAlmostEqual(result.notes[0].end_time, 0.78, places=3)
        self.assertIn(SHORT_NOTE_ABSORBED, result.notes[0].reason_codes)
        self.assertEqual(result.postprocess_action_counts["short_note_absorb"], 1)

    def test_corrects_octave_spike_within_phrase(self):
        selector = MelodySelector(
            PitchDetectionConfig(
                melody_min_confidence=0.5,
                melody_short_note_min_confidence=0.5,
                melody_merge_gap_sec=0.08,
                melody_merge_pitch_tolerance_semitones=1,
                melody_large_jump_semitones=12,
            )
        )
        notes = [
            Note(pitch="C4", start_time=0.00, end_time=0.30, confidence=0.90),
            Note(pitch="C5", start_time=0.33, end_time=0.41, confidence=0.54),
            Note(pitch="C4", start_time=0.44, end_time=0.79, confidence=0.91),
        ]

        result = selector.select(notes)

        self.assertEqual(result.kept_count, 1)
        self.assertEqual(result.notes[0].pitch, "C4")
        self.assertAlmostEqual(result.notes[0].end_time, 0.79, places=3)
        self.assertIn(OCTAVE_JUMP_CORRECTED, result.postprocess_reason_code_counts)

    def test_smooths_short_inner_pitch_outlier_without_deleting_note(self):
        selector = MelodySelector(
            PitchDetectionConfig(
                melody_min_confidence=0.5,
                melody_short_note_min_confidence=0.5,
                melody_merge_gap_sec=0.08,
                melody_merge_pitch_tolerance_semitones=1,
            )
        )
        notes = [
            Note(pitch="E4", start_time=0.00, end_time=0.28, confidence=0.89),
            Note(pitch="F#4", start_time=0.31, end_time=0.43, confidence=0.57),
            Note(pitch="E4", start_time=0.46, end_time=0.76, confidence=0.88),
        ]

        result = selector.select(notes)

        self.assertEqual(result.kept_count, 1)
        self.assertEqual(result.notes[0].pitch, "E4")
        self.assertAlmostEqual(result.notes[0].start_time, 0.00, places=3)
        self.assertAlmostEqual(result.notes[0].end_time, 0.76, places=3)


if __name__ == "__main__":
    unittest.main()
