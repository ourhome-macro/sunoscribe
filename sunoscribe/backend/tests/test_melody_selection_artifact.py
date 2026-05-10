from __future__ import annotations

import unittest

from app.modules.pitch.melody_selection_artifact import RuleBasedMelodySelector
from app.modules.pitch.reason_codes import LOW_CONFIDENCE, OUTSIDE_VOCAL_RANGE, OVERLAPS_STRONGER_CANDIDATE, TOO_SHORT


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


if __name__ == "__main__":
    unittest.main()
