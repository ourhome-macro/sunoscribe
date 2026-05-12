from __future__ import annotations

import unittest

from app.modules.pitch.melody_selection_artifact import RuleBasedMelodySelector
from app.modules.pitch.reason_codes import (
    LOW_CONFIDENCE,
    OCTAVE_JUMP_CORRECTED,
    OUTSIDE_VOCAL_RANGE,
    OVERLAPS_STRONGER_CANDIDATE,
    PHRASE_MEDIAN_SMOOTHED,
    SHORT_GAP_BRIDGED,
    SHORT_NOTE_ABSORBED,
    TOO_SHORT,
)


class TestRuleBasedMelodySelector(unittest.TestCase):
    def test_rejects_low_confidence_short_and_out_of_range(self) -> None:
        selector = RuleBasedMelodySelector()
        result = selector.select(
            note_candidates={
                "melody_candidates": {
                    "notes": [
                        {"id": "low", "start_time": 0.0, "end_time": 0.5, "pitch": "C4", "confidence": 0.1},
                        {"id": "short", "start_time": 1.0, "end_time": 1.05, "pitch": "C4", "confidence": 0.9},
                        {"id": "range", "start_time": 2.0, "end_time": 2.5, "pitch_midi": 96, "confidence": 0.9},
                    ]
                }
            }
        )

        reasons = {item["candidate_id"]: set(item["reason_codes"]) for item in result["rejected_candidates"]}
        self.assertIn(LOW_CONFIDENCE, reasons["low"])
        self.assertIn(TOO_SHORT, reasons["short"])
        self.assertIn(OUTSIDE_VOCAL_RANGE, reasons["range"])

    def test_overlap_keeps_stronger_candidate(self) -> None:
        result = RuleBasedMelodySelector().select(
            note_candidates={
                "melody_candidates": {
                    "notes": [
                        {"id": "strong", "start_time": 0.0, "end_time": 0.5, "pitch": "C4", "confidence": 0.9},
                        {"id": "weak", "start_time": 0.1, "end_time": 0.6, "pitch": "D4", "confidence": 0.7},
                    ]
                }
            }
        )

        self.assertEqual([item["candidate_id"] for item in result["selected_notes"]], ["strong"])
        self.assertEqual(result["summary"]["selected_count"], 1)
        self.assertEqual(result["summary"]["rejected_count"], 1)
        self.assertIn(OVERLAPS_STRONGER_CANDIDATE, result["rejected_candidates"][0]["reason_codes"])

    def test_phrase_postprocess_bridges_short_gap_and_records_reason(self) -> None:
        result = RuleBasedMelodySelector().select(
            note_candidates={
                "melody_candidates": {
                    "notes": [
                        {"id": "a", "start_time": 0.0, "end_time": 0.30, "pitch": "C4", "confidence": 0.9},
                        {"id": "b", "start_time": 0.35, "end_time": 0.70, "pitch": "C4", "confidence": 0.88},
                    ]
                }
            }
        )

        self.assertEqual(result["summary"]["selected_count"], 1)
        note = result["selected_notes"][0]
        self.assertAlmostEqual(note["start_time_sec"], 0.0, places=3)
        self.assertAlmostEqual(note["end_time_sec"], 0.7, places=3)
        self.assertIn(SHORT_GAP_BRIDGED, note["reason_codes"])
        self.assertEqual(result["postprocess"]["action_counts"]["short_gap_bridge"], 1)

    def test_phrase_postprocess_absorbs_short_note_and_corrects_octave(self) -> None:
        result = RuleBasedMelodySelector().select(
            note_candidates={
                "melody_candidates": {
                    "notes": [
                        {"id": "left", "start_time": 0.00, "end_time": 0.30, "pitch": "C4", "confidence": 0.9},
                        {"id": "spike", "start_time": 0.33, "end_time": 0.46, "pitch": "C5", "confidence": 0.55},
                        {"id": "right", "start_time": 0.49, "end_time": 0.82, "pitch": "C4", "confidence": 0.91},
                    ]
                }
            }
        )

        self.assertEqual(result["summary"]["selected_count"], 1)
        note = result["selected_notes"][0]
        self.assertEqual(round(note["pitch_center_midi"]), 60)
        self.assertIn(SHORT_NOTE_ABSORBED, note["reason_codes"])
        self.assertIn(OCTAVE_JUMP_CORRECTED, result["postprocess"]["reason_code_counts"])
        self.assertEqual(result["postprocess"]["action_counts"]["short_note_absorb"], 1)

    def test_phrase_postprocess_median_smooths_inner_outlier(self) -> None:
        result = RuleBasedMelodySelector().select(
            note_candidates={
                "melody_candidates": {
                    "notes": [
                        {"id": "n1", "start_time": 0.00, "end_time": 0.22, "pitch": "E4", "confidence": 0.90},
                        {"id": "n2", "start_time": 0.25, "end_time": 0.47, "pitch": "E4", "confidence": 0.90},
                        {"id": "n3", "start_time": 0.50, "end_time": 0.62, "pitch": "F#4", "confidence": 0.58},
                        {"id": "n4", "start_time": 0.65, "end_time": 0.87, "pitch": "E4", "confidence": 0.90},
                        {"id": "n5", "start_time": 0.90, "end_time": 1.12, "pitch": "E4", "confidence": 0.90},
                    ]
                }
            }
        )

        selected = result["selected_notes"]
        self.assertTrue(any(PHRASE_MEDIAN_SMOOTHED in note["reason_codes"] for note in selected))
        smoothed = [note for note in selected if PHRASE_MEDIAN_SMOOTHED in note["reason_codes"]][0]
        self.assertEqual(round(smoothed["pitch_center_midi"]), 64)
        self.assertEqual(result["postprocess"]["action_counts"]["median_smoothing"], 1)

    def test_phrase_postprocess_does_not_repair_cross_phrase_large_jump(self) -> None:
        result = RuleBasedMelodySelector().select(
            note_candidates={
                "melody_candidates": {
                    "notes": [
                        {"id": "low", "start_time": 0.0, "end_time": 0.30, "pitch": "C4", "confidence": 0.9},
                        {"id": "high", "start_time": 1.10, "end_time": 1.40, "pitch": "C5", "confidence": 0.9},
                        {"id": "next", "start_time": 2.20, "end_time": 2.50, "pitch": "D5", "confidence": 0.9},
                    ]
                }
            }
        )

        self.assertEqual([round(note["pitch_center_midi"]) for note in result["selected_notes"]], [60, 72, 74])
        self.assertNotIn(OCTAVE_JUMP_CORRECTED, result["summary"].get("selected_reason_counts", {}))

    def test_phrase_postprocess_corrects_short_octave_island_with_local_anchors(self) -> None:
        result = RuleBasedMelodySelector().select(
            note_candidates={
                "melody_candidates": {
                    "notes": [
                        {"id": "n1", "start_time": 0.00, "end_time": 0.28, "pitch": "A4", "confidence": 0.91},
                        {"id": "n2", "start_time": 0.31, "end_time": 0.52, "pitch": "A5", "confidence": 0.55},
                        {"id": "n3", "start_time": 0.55, "end_time": 0.76, "pitch": "A5", "confidence": 0.56},
                        {"id": "n4", "start_time": 0.79, "end_time": 1.08, "pitch": "G4", "confidence": 0.92},
                    ]
                }
            }
        )

        selected = result["selected_notes"]
        corrected = [note for note in selected if OCTAVE_JUMP_CORRECTED in note["reason_codes"]]
        self.assertTrue(corrected)
        self.assertLessEqual(max(abs(round(note["pitch_center_midi"]) - 69) for note in corrected), 2)
        self.assertEqual(result["postprocess"]["action_counts"]["octave_jump_correction"], len(corrected))


if __name__ == "__main__":
    unittest.main()
