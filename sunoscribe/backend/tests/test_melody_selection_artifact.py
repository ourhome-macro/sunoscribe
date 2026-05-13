from __future__ import annotations

import unittest

from app.modules.pitch.melody_selection_artifact import MelodySelectionConfig, RuleBasedMelodySelector
from app.modules.pitch.reason_codes import (
    ISOLATED_FRAGMENT_REMOVED,
    LOW_CONFIDENCE,
    OCTAVE_JUMP_CORRECTED,
    OUTSIDE_VOCAL_RANGE,
    OVERLAPS_STRONGER_CANDIDATE,
    PHRASE_MEDIAN_SMOOTHED,
    PHRASE_GAP_SUSTAINED,
    SHORT_GAP_BRIDGED,
    SHORT_NOTE_ABSORBED,
    TOO_SHORT,
)


class TestRuleBasedMelodySelector(unittest.TestCase):
    def test_preselected_notes_are_preferred_by_default_and_marked(self) -> None:
        result = RuleBasedMelodySelector(MelodySelectionConfig(phrase_postprocess_enabled=False)).select(
            note_candidates={
                "melody_candidates": {
                    "notes": [
                        {"id": "raw", "start_time": 0.0, "end_time": 0.4, "pitch": "C4", "confidence": 0.9},
                    ],
                    "selected_notes": [
                        {
                            "id": "legacy",
                            "start_time": 1.0,
                            "end_time": 1.4,
                            "pitch": "D4",
                            "confidence": 0.9,
                            "reason_codes": [SHORT_GAP_BRIDGED],
                        },
                    ],
                }
            }
        )

        self.assertEqual([note["candidate_id"] for note in result["selected_notes"]], ["legacy"])
        self.assertEqual(result["summary"]["input_source"], "melody_candidates.selected_notes_preselected")
        self.assertEqual(result["config"]["input_source"], "melody_candidates.selected_notes_preselected")
        self.assertEqual(result["summary"]["inherited_reason_code_counts"], {SHORT_GAP_BRIDGED: 1})

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
        self.assertEqual(result["postprocess"]["enabled"], True)
        self.assertEqual(result["postprocess"]["input_note_count"], 2)
        self.assertEqual(result["postprocess"]["output_note_count"], 1)
        self.assertEqual(result["postprocess"]["action_counts"]["short_gap_bridge"], 1)
        action = result["postprocess"]["actions"][0]
        self.assertEqual(action["action"], "short_gap_bridge")
        self.assertEqual(action["reason_code"], SHORT_GAP_BRIDGED)
        self.assertEqual(action["note_ids"], ["a", "b"])
        self.assertEqual(action["output_note_id"], "a+b")
        self.assertEqual(action["details"]["mode"], "merge_no_insert")

    def test_phrase_postprocess_disabled_keeps_candidates_and_reports_disabled(self) -> None:
        result = RuleBasedMelodySelector(
            MelodySelectionConfig(phrase_postprocess_enabled=False)
        ).select(
            note_candidates={
                "melody_candidates": {
                    "notes": [
                        {"id": "a", "start_time": 0.0, "end_time": 0.30, "pitch": "C4", "confidence": 0.9},
                        {"id": "b", "start_time": 0.35, "end_time": 0.70, "pitch": "C4", "confidence": 0.88},
                    ]
                }
            }
        )

        self.assertEqual(result["summary"]["selected_count"], 2)
        self.assertEqual(result["postprocess"]["enabled"], False)
        self.assertEqual(result["postprocess"]["input_note_count"], 2)
        self.assertEqual(result["postprocess"]["output_note_count"], 2)
        self.assertEqual(result["postprocess"]["action_count"], 0)

    def test_phrase_postprocess_does_not_insert_bridge_note_between_distant_pitches(self) -> None:
        result = RuleBasedMelodySelector().select(
            note_candidates={
                "melody_candidates": {
                    "notes": [
                        {"id": "a", "start_time": 0.0, "end_time": 0.30, "pitch": "C4", "confidence": 0.9},
                        {"id": "b", "start_time": 0.35, "end_time": 0.70, "pitch": "E4", "confidence": 0.9},
                    ]
                }
            }
        )

        self.assertEqual(result["summary"]["selected_count"], 2)
        self.assertEqual([note["candidate_id"] for note in result["selected_notes"]], ["a", "b"])
        self.assertEqual(result["postprocess"]["output_note_count"], result["postprocess"]["input_note_count"])
        self.assertNotIn(SHORT_GAP_BRIDGED, result["summary"].get("selected_reason_counts", {}))

    def test_phrase_postprocess_removes_weak_isolated_fragment(self) -> None:
        result = RuleBasedMelodySelector(
            MelodySelectionConfig(postprocess_profile="cleanup_aggressive", phrase_remove_isolated_fragments_enabled=True)
        ).select(
            note_candidates={
                "melody_candidates": {
                    "notes": [
                        {"id": "left", "start_time": 0.00, "end_time": 0.30, "pitch": "C4", "confidence": 0.9},
                        {"id": "bad", "start_time": 0.34, "end_time": 0.46, "pitch": "C5", "confidence": 0.53},
                        {"id": "right", "start_time": 0.50, "end_time": 0.82, "pitch": "C4", "confidence": 0.9},
                    ]
                }
            }
        )

        self.assertEqual([note["candidate_id"] for note in result["selected_notes"]], ["left", "right"])
        self.assertEqual(result["postprocess"]["action_counts"]["isolated_fragment_remove"], 1)
        action = [action for action in result["postprocess"]["actions"] if action["action"] == "isolated_fragment_remove"][0]
        self.assertEqual(action["reason_code"], ISOLATED_FRAGMENT_REMOVED)
        self.assertEqual(action["note_ids"], ["bad"])
        self.assertEqual(action["details"]["profile"], "cleanup_aggressive")
        self.assertEqual(action["details"]["mode"], "delete_weak_short_local_outlier")

    def test_phrase_postprocess_keeps_confident_isolated_note(self) -> None:
        result = RuleBasedMelodySelector(
            MelodySelectionConfig(postprocess_profile="cleanup_aggressive", phrase_remove_isolated_fragments_enabled=True)
        ).select(
            note_candidates={
                "melody_candidates": {
                    "notes": [
                        {"id": "left", "start_time": 0.00, "end_time": 0.30, "pitch": "C4", "confidence": 0.9},
                        {"id": "real", "start_time": 0.34, "end_time": 0.46, "pitch": "C5", "confidence": 0.82},
                        {"id": "right", "start_time": 0.50, "end_time": 0.82, "pitch": "C4", "confidence": 0.9},
                    ]
                }
            }
        )

        self.assertIn("real", [note["candidate_id"] for note in result["selected_notes"]])
        self.assertNotIn(ISOLATED_FRAGMENT_REMOVED, result["postprocess"].get("reason_code_counts", {}))

    def test_phrase_postprocess_sustains_short_phrase_gap_for_playback_continuity(self) -> None:
        result = RuleBasedMelodySelector().select(
            note_candidates={
                "melody_candidates": {
                    "notes": [
                        {"id": "a", "start_time": 0.00, "end_time": 0.30, "pitch": "C4", "confidence": 0.9},
                        {"id": "b", "start_time": 0.41, "end_time": 0.72, "pitch": "D4", "confidence": 0.9},
                    ]
                }
            }
        )

        self.assertEqual(result["summary"]["selected_count"], 2)
        first = result["selected_notes"][0]
        self.assertAlmostEqual(first["end_time_sec"], 0.41, places=3)
        self.assertIn(PHRASE_GAP_SUSTAINED, first["reason_codes"])
        self.assertEqual(result["postprocess"]["action_counts"]["phrase_gap_sustain"], 1)

    def test_phrase_postprocess_absorbs_short_note_and_corrects_octave(self) -> None:
        result = RuleBasedMelodySelector(
            MelodySelectionConfig(postprocess_profile="cleanup_aggressive", phrase_remove_isolated_fragments_enabled=True)
        ).select(
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

        self.assertEqual(result["summary"]["selected_count"], 2)
        self.assertEqual([note["candidate_id"] for note in result["selected_notes"]], ["left", "right"])
        self.assertEqual(result["postprocess"]["action_counts"]["isolated_fragment_remove"], 1)
        remove_action = [
            action for action in result["postprocess"]["actions"] if action["action"] == "isolated_fragment_remove"
        ][0]
        self.assertEqual(remove_action["reason_code"], ISOLATED_FRAGMENT_REMOVED)
        self.assertEqual(remove_action["details"]["profile"], "cleanup_aggressive")
        self.assertEqual(remove_action["details"]["mode"], "delete_weak_short_local_outlier")
        self.assertGreater(remove_action["details"]["jump_from_prev_semitones"], 7)

    def test_default_conservative_profile_keeps_weak_isolated_fragment(self) -> None:
        result = RuleBasedMelodySelector().select(
            note_candidates={
                "melody_candidates": {
                    "notes": [
                        {"id": "left", "start_time": 0.00, "end_time": 0.30, "pitch": "C4", "confidence": 0.9},
                        {"id": "bad", "start_time": 0.34, "end_time": 0.46, "pitch": "C5", "confidence": 0.53},
                        {"id": "right", "start_time": 0.50, "end_time": 0.82, "pitch": "C4", "confidence": 0.9},
                    ]
                }
            }
        )

        self.assertFalse(result["config"]["phrase_remove_isolated_fragments_enabled"])
        self.assertNotIn("isolated_fragment_remove", result["postprocess"]["action_counts"])
        self.assertNotIn(ISOLATED_FRAGMENT_REMOVED, result["postprocess"]["reason_code_counts"])

    def test_raw_notes_are_preferred_over_legacy_selected_notes(self) -> None:
        result = RuleBasedMelodySelector(MelodySelectionConfig(phrase_postprocess_enabled=False)).select(
            note_candidates={
                "melody_candidates": {
                    "notes": [
                        {"id": "raw", "start_time": 0.0, "end_time": 0.4, "pitch": "C4", "confidence": 0.9},
                    ],
                    "selected_notes": [
                        {
                            "id": "legacy",
                            "start_time": 1.0,
                            "end_time": 1.4,
                            "pitch": "D4",
                            "confidence": 0.9,
                            "reason_codes": [SHORT_GAP_BRIDGED],
                        },
                    ],
                }
            }
        )

        self.assertEqual([note["candidate_id"] for note in result["selected_notes"]], ["legacy"])
        self.assertEqual(result["summary"]["input_source"], "melody_candidates.selected_notes_preselected")
        self.assertTrue(result["summary"]["prefer_preselected_notes"])
        self.assertEqual(result["summary"]["inherited_reason_code_counts"], {SHORT_GAP_BRIDGED: 1})

    def test_raw_notes_can_be_forced_for_diagnostic_review(self) -> None:
        result = RuleBasedMelodySelector(
            MelodySelectionConfig(phrase_postprocess_enabled=False, prefer_preselected_notes=False)
        ).select(
            note_candidates={
                "melody_candidates": {
                    "notes": [
                        {"id": "raw", "start_time": 0.0, "end_time": 0.4, "pitch": "C4", "confidence": 0.9},
                    ],
                    "selected_notes": [
                        {
                            "id": "legacy",
                            "start_time": 1.0,
                            "end_time": 1.4,
                            "pitch": "D4",
                            "confidence": 0.9,
                            "reason_codes": [SHORT_GAP_BRIDGED],
                        },
                    ],
                }
            }
        )

        self.assertEqual([note["candidate_id"] for note in result["selected_notes"]], ["raw"])
        self.assertEqual(result["summary"]["input_source"], "melody_candidates.notes")
        self.assertFalse(result["summary"]["prefer_preselected_notes"])
        self.assertEqual(result["summary"]["inherited_reason_code_counts"], {})

    def test_legacy_selected_notes_reason_codes_are_inherited_not_actions(self) -> None:
        result = RuleBasedMelodySelector(MelodySelectionConfig(phrase_postprocess_enabled=False)).select(
            note_candidates={
                "melody_candidates": {
                    "selected_notes": [
                        {
                            "id": "legacy",
                            "start_time": 1.0,
                            "end_time": 1.4,
                            "pitch": "D4",
                            "confidence": 0.9,
                            "reason_codes": [SHORT_GAP_BRIDGED],
                        },
                    ],
                }
            }
        )

        self.assertEqual(result["summary"]["input_source"], "melody_candidates.selected_notes_preselected")
        self.assertEqual(result["summary"]["inherited_reason_code_counts"], {SHORT_GAP_BRIDGED: 1})
        self.assertEqual(result["postprocess"]["inherited_reason_code_counts"], {SHORT_GAP_BRIDGED: 1})
        self.assertEqual(result["postprocess"]["action_count"], 0)
        self.assertEqual(result["postprocess"]["action_counts"], {})
        self.assertEqual(result["postprocess"]["reason_code_counts"], {})
        self.assertEqual(result["summary"]["postprocess_action_counts"], {})
        self.assertEqual(result["summary"]["postprocess_reason_code_counts"], {})

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
