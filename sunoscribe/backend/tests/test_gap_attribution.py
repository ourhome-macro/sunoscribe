from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.modules.benchmark.gap_attribution import build_gap_attribution
from app.modules.benchmark.midi_metrics import MidiMetricConfig, NoteEvent
from app.modules.benchmark.reason_codes import (
    CANDIDATE_FORMATION_LOW_OCTAVE_CLUSTER,
    CANDIDATE_FORMATION_SPLITS_BIG_GAP,
    DEBUG_ATTR_BRIDGE_SEGMENTATION_REJECTED,
    DEBUG_ATTR_SELECTOR_REJECTED_UNSTABLE_SEGMENT,
    DEBUG_ATTR_SELECTOR_REJECTED_WEAK_SEGMENT,
    GAP_ATTR_CANDIDATE_EXISTS_SELECTOR_REMOVED,
    GAP_ATTR_F0_EXISTS_NO_CANDIDATE,
    GAP_ATTR_QUANTIZATION_EXPORT_INDUCED,
    GAP_ATTR_RAW_F0_MISSING,
    LOST_EXPECTED_CANDIDATE_EXISTS_SELECTOR_REMOVED,
    LOST_EXPECTED_F0_EXISTS_NO_CANDIDATE,
    LOST_EXPECTED_QUANTIZATION_EXPORT_INDUCED,
    LOST_EXPECTED_RAW_F0_MISSING,
    DELETED_CANDIDATE_SELECTOR_REMOVED,
    SELECTOR_STAGE_PITCH_RANGE,
)


class GapAttributionTests(unittest.TestCase):
    def test_candidate_exists_but_selector_removed(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidates = root / "note_candidates.json"
            selected = root / "selected_melody.json"
            _write_json(
                candidates,
                {
                    "melody_candidates": {
                        "notes": [
                            _candidate("raw_1", 0.0, 0.4, 60, confidence=0.9),
                            _candidate("raw_2", 1.0, 1.4, 62, confidence=0.8),
                        ]
                    }
                },
            )
            _write_json(selected, {"selected_notes": [_selected("cand_1", 0.0, 0.4, 60)]})

            result = build_gap_attribution(
                expected_notes=[_note(1.0, 1.4, 62)],
                predicted_notes=[_note(0.0, 0.4, 60)],
                f0_track_path=None,
                vocal_activity_path=None,
                pitch_contours_path=None,
                note_candidates_path=candidates,
                selected_melody_path=selected,
                quantized_notes_path=None,
                score_ir_path=None,
                config=MidiMetricConfig(auto_octave_normalize=False),
            )

            self.assertEqual(result["top_lost_expected_notes"][0]["classification"], GAP_ATTR_CANDIDATE_EXISTS_SELECTOR_REMOVED)
            self.assertEqual(result["top_lost_expected_notes"][0]["reason_codes"], [LOST_EXPECTED_CANDIDATE_EXISTS_SELECTOR_REMOVED])
            self.assertEqual(result["top_deleted_candidates"][0]["diagnostic_reason_codes"][0], DELETED_CANDIDATE_SELECTOR_REMOVED)
            self.assertTrue(result["diagnostic_only"])
            self.assertFalse(result["production_mutation_allowed"])
            self.assertTrue(result["reference_midi_used_for_benchmark_attribution_only"])
            for key in ("version", "layer_summary", "retention", "reason_counts", "recommended_fix_focus"):
                self.assertIn(key, result)

    def test_gap_selector_removed_includes_selector_stage_reason_counts(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidates = root / "note_candidates.json"
            selected = root / "selected_melody.json"
            _write_json(
                candidates,
                {
                    "melody_candidates": {
                        "notes": [
                            _candidate("raw_left", 0.0, 0.4, 60, confidence=0.9),
                            _candidate("raw_low", 1.0, 1.3, 46, confidence=0.8),
                            _candidate("raw_right", 2.0, 2.4, 64, confidence=0.9),
                        ]
                    }
                },
            )
            _write_json(
                selected,
                {
                    "selected_notes": [
                        _selected("raw_left", 0.0, 0.4, 60),
                        _selected("raw_right", 2.0, 2.4, 64),
                    ],
                    "rejected_candidates": [
                        {
                            **_candidate("raw_low", 1.0, 1.3, 46, confidence=0.8),
                            "segmentation_evidence": {
                                "backend": "rmvpe",
                                "start_frame_index": 100,
                                "end_frame_index": 130,
                                "frame_hop_sec": 0.01,
                                "quality_factor": 0.42,
                                "mad_semitones": 1.2,
                                "span_semitones": 3.4,
                            },
                        }
                    ],
                },
            )

            result = build_gap_attribution(
                expected_notes=[],
                predicted_notes=[_note(0.0, 0.4, 60), _note(2.0, 2.4, 64)],
                f0_track_path=None,
                vocal_activity_path=None,
                pitch_contours_path=None,
                note_candidates_path=candidates,
                selected_melody_path=selected,
                quantized_notes_path=None,
                score_ir_path=None,
                config=MidiMetricConfig(auto_octave_normalize=False),
            )

            gap_evidence = result["top_gaps"][0]["evidence"]
            self.assertEqual(gap_evidence["selector_stage_reason_counts"], {SELECTOR_STAGE_PITCH_RANGE: 1})
            self.assertEqual(gap_evidence["top_selector_removed_candidates"][0]["selector_stage_reason"], SELECTOR_STAGE_PITCH_RANGE)
            debug_summary = gap_evidence["debug_attribution"]["selector_rejected_segmentation_summary"]
            self.assertEqual(debug_summary["quality_factor_stats"]["median"], 0.42)
            self.assertEqual(debug_summary["span_semitones_stats"]["median"], 3.4)
            self.assertIn(DEBUG_ATTR_SELECTOR_REJECTED_WEAK_SEGMENT, debug_summary["reason_codes"])
            self.assertIn(DEBUG_ATTR_SELECTOR_REJECTED_UNSTABLE_SEGMENT, debug_summary["reason_codes"])
            compact_evidence = debug_summary["examples"][0]["segmentation_evidence"]
            self.assertEqual(compact_evidence["start_frame_index"], 100)
            self.assertEqual(compact_evidence["frame_hop_sec"], 0.01)

    def test_gap_selector_removed_includes_candidate_formation_opportunity(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidates = root / "note_candidates.json"
            selected = root / "selected_melody.json"
            _write_json(
                candidates,
                {
                    "melody_candidates": {
                        "notes": [
                            _candidate("raw_left", 0.0, 0.3, 58, confidence=0.9),
                            _candidate("raw_low_1", 1.1, 1.3, 46, confidence=0.7),
                            _candidate("raw_low_2", 1.5, 1.7, 46, confidence=0.7),
                            _candidate("raw_right", 2.5, 2.8, 58, confidence=0.9),
                        ]
                    }
                },
            )
            _write_json(
                selected,
                {
                    "selected_notes": [
                        _selected("raw_left", 0.0, 0.3, 58),
                        _selected("raw_right", 2.5, 2.8, 58),
                    ]
                },
            )

            result = build_gap_attribution(
                expected_notes=[],
                predicted_notes=[_note(0.0, 0.3, 58), _note(2.5, 2.8, 58)],
                f0_track_path=None,
                vocal_activity_path=None,
                pitch_contours_path=None,
                note_candidates_path=candidates,
                selected_melody_path=selected,
                quantized_notes_path=None,
                score_ir_path=None,
                config=MidiMetricConfig(auto_octave_normalize=False),
            )

            opportunity = result["top_gaps"][0]["evidence"]["candidate_formation_opportunity"]
            self.assertEqual(opportunity["candidate_count"], 2)
            self.assertEqual(opportunity["pitch_center_midi"], 46.0)
            self.assertEqual(opportunity["shifted_pitch_center_midi"], 58.0)
            self.assertIn(CANDIDATE_FORMATION_LOW_OCTAVE_CLUSTER, opportunity["reason_codes"])
            self.assertIn(CANDIDATE_FORMATION_SPLITS_BIG_GAP, opportunity["reason_codes"])

    def test_f0_exists_but_no_candidate(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            f0_track = root / "f0_track.json"
            candidates = root / "note_candidates.json"
            _write_json(f0_track, {"frames": [_frame(t, 64, 0.9, True) for t in [1.0, 1.1, 1.2, 1.3]]})
            _write_json(candidates, {"melody_candidates": {"notes": []}})

            result = build_gap_attribution(
                expected_notes=[_note(1.0, 1.35, 64)],
                predicted_notes=[],
                f0_track_path=f0_track,
                vocal_activity_path=None,
                pitch_contours_path=None,
                note_candidates_path=candidates,
                selected_melody_path=None,
                quantized_notes_path=None,
                score_ir_path=None,
                config=MidiMetricConfig(auto_octave_normalize=False),
            )

            self.assertEqual(result["top_lost_expected_notes"][0]["classification"], GAP_ATTR_F0_EXISTS_NO_CANDIDATE)
            self.assertEqual(result["top_lost_expected_notes"][0]["reason_codes"], [LOST_EXPECTED_F0_EXISTS_NO_CANDIDATE])

    def test_contour_to_candidate_bridge_summary_is_diagnostic_only(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidates = root / "note_candidates.json"
            _write_json(
                candidates,
                {
                    "melody_candidates": {
                        "notes": [
                            {
                                **_candidate("contour_bridge:pc_1", 1.0, 1.3, 62, confidence=0.9),
                                "candidate_origin": "contour_to_candidate_bridge",
                                "reason_codes": ["contour_to_candidate_bridge", "bridge_from_f0_contour"],
                                "contour_bridge_guard_reason_codes": ["contour_candidate_context_guarded"],
                            }
                        ],
                        "selected_notes": [
                            {
                                **_selected("contour_bridge:pc_1", 1.0, 1.3, 62),
                                "candidate_origin": "contour_to_candidate_bridge",
                                "reason_codes": ["contour_to_candidate_bridge", "bridge_from_f0_contour"],
                            }
                        ],
                        "analysis_info": {
                            "contour_to_candidate_bridge": {
                                "version": "contour_to_candidate_bridge_v1",
                                "enabled": True,
                                "candidate_count": 2,
                                "accepted_count": 1,
                                "rejected_count": 1,
                                "guard_reason_counts": {"contour_candidate_context_guarded": 1, "low_confidence": 1},
                                "accepted_candidates": [
                                    {
                                        "candidate_id": "contour_bridge:pc_1",
                                        "source_contour_id": "pc_1",
                                        "start_time_sec": 1.0,
                                        "end_time_sec": 1.3,
                                        "duration_sec": 0.3,
                                        "pitch_center_midi": 62,
                                        "confidence": 0.9,
                                        "reason_codes": ["contour_to_candidate_bridge"],
                                        "contour_bridge_guard_reason_codes": [],
                                        "evidence": {"raw_overlap_duration_sec": 0.0},
                                    }
                                ],
                                "rejected_candidates": [],
                            }
                        },
                    }
                },
            )

            result = build_gap_attribution(
                expected_notes=[_note(1.0, 1.3, 62)],
                predicted_notes=[_note(1.0, 1.3, 62)],
                f0_track_path=None,
                vocal_activity_path=None,
                pitch_contours_path=None,
                note_candidates_path=candidates,
                selected_melody_path=None,
                quantized_notes_path=None,
                score_ir_path=None,
                config=MidiMetricConfig(auto_octave_normalize=False),
            )

            bridge = result["contour_to_candidate_bridge"]
            self.assertTrue(bridge["available"])
            self.assertEqual(bridge["accepted_count"], 1)
            self.assertEqual(bridge["raw_bridge_candidate_count"], 1)
            self.assertEqual(bridge["selected_bridge_candidate_count"], 1)
            self.assertFalse(result["production_mutation_allowed"])

    def test_gap_attribution_includes_contour_bridge_segmentation_rejection_summary(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            f0_track = root / "f0_track.json"
            pitch_contours = root / "pitch_contours.json"
            candidates = root / "note_candidates.json"
            _write_json(f0_track, {"frames": [_frame(t, 72, 0.9, True) for t in [1.0, 1.1, 1.2, 1.3, 1.4]]})
            _write_json(
                pitch_contours,
                {
                    "contours": [
                        {
                            "id": "pc_gap",
                            "start_time_sec": 1.0,
                            "end_time_sec": 1.5,
                            "duration_sec": 0.5,
                            "pitch_center_midi": 72,
                            "mean_confidence": 0.9,
                        }
                    ]
                },
            )
            _write_json(
                candidates,
                {
                    "melody_candidates": {
                        "notes": [],
                        "analysis_info": {
                            "contour_to_candidate_bridge": {
                                "version": "contour_to_candidate_bridge_v1",
                                "enabled": True,
                                "candidate_count": 1,
                                "accepted_count": 0,
                                "rejected_count": 1,
                                "guard_reason_counts": {"contour_candidate_no_local_context": 1},
                                "accepted_candidates": [],
                                "rejected_candidates": [
                                    {
                                        "candidate_id": "contour_bridge:pc_gap",
                                        "source_contour_id": "pc_gap",
                                        "start_time_sec": 1.0,
                                        "end_time_sec": 1.5,
                                        "duration_sec": 0.5,
                                        "pitch_center_midi": 72,
                                        "confidence": 0.9,
                                        "reason_codes": ["contour_to_candidate_bridge", "bridge_from_f0_contour"],
                                        "contour_bridge_guard_reason_codes": ["contour_candidate_no_local_context"],
                                        "evidence": {
                                            "source_contour_id": "pc_gap",
                                            "raw_overlap_duration_sec": 0.0,
                                            "nearest_raw_gap": {
                                                "start_time_sec": 0.6,
                                                "end_time_sec": 2.2,
                                                "duration_sec": 1.6,
                                            },
                                            "segmentation_attempt_summary": {
                                                "enabled": True,
                                                "candidate_count": 1,
                                                "attempted_count": 1,
                                                "accepted_count": 0,
                                                "rejected_count": 1,
                                                "reason_codes": ["contour_segmentation_all_segments_rejected"],
                                                "guard_reason_counts": {"contour_candidate_no_local_context": 1},
                                                "attempts": [
                                                    {
                                                        "candidate_id": "contour_segment_bridge:pc_gap:seg_01",
                                                        "start_time_sec": 1.1,
                                                        "end_time_sec": 1.35,
                                                        "duration_sec": 0.25,
                                                        "pitch_center_midi": 72,
                                                        "confidence": 0.91,
                                                        "guard_reason_codes": ["contour_candidate_no_local_context"],
                                                        "raw_overlap_duration_sec": 0.0,
                                                        "segmentation_evidence": {
                                                            "segment_index": 1,
                                                            "segment_frame_count": 8,
                                                            "segment_pitch_range_semitones": 0.4,
                                                            "segment_mean_confidence": 0.91,
                                                        },
                                                    }
                                                ],
                                            },
                                        },
                                    }
                                ],
                            }
                        },
                    }
                },
            )

            result = build_gap_attribution(
                expected_notes=[_note(1.0, 1.5, 72)],
                predicted_notes=[_note(0.0, 0.5, 60), _note(2.2, 2.6, 62)],
                f0_track_path=f0_track,
                vocal_activity_path=None,
                pitch_contours_path=pitch_contours,
                note_candidates_path=candidates,
                selected_melody_path=None,
                quantized_notes_path=None,
                score_ir_path=None,
                config=MidiMetricConfig(auto_octave_normalize=False),
            )

            gap = result["top_gaps"][0]
            self.assertEqual(gap["classification"], GAP_ATTR_F0_EXISTS_NO_CANDIDATE)
            evidence = gap["evidence"]
            self.assertEqual(evidence["raw_candidates_in_gap"], 0)
            self.assertEqual(evidence["contour_bridge_rejections_in_gap"], 1)
            rejection = evidence["top_contour_bridge_rejections"][0]
            self.assertEqual(rejection["source_contour_id"], "pc_gap")
            self.assertEqual(rejection["guard_reason_codes"], ["contour_candidate_no_local_context"])
            summary = evidence["top_contour_bridge_segmentation_summaries"][0]
            self.assertEqual(summary["reason_codes"], ["contour_segmentation_all_segments_rejected"])
            self.assertEqual(summary["attempt_guard_reason_counts"], {"contour_candidate_no_local_context": 1})
            self.assertEqual(summary["attempts"][0]["segment_frame_count"], 8)
            debug_summary = evidence["debug_attribution"]["bridge_rejected_segmentation_summary"]
            self.assertIn(DEBUG_ATTR_BRIDGE_SEGMENTATION_REJECTED, debug_summary["reason_codes"])
            self.assertEqual(debug_summary["guard_reason_counts"], {"contour_candidate_no_local_context": 2})
            self.assertTrue(result["diagnostic_only"])
            self.assertFalse(result["production_mutation_allowed"])

    def test_raw_f0_missing_inside_vocal_activity(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            f0_track = root / "f0_track.json"
            vocal_activity = root / "vocal_activity.json"
            candidates = root / "note_candidates.json"
            _write_json(f0_track, {"frames": [_frame(t, 60, 0.05, False) for t in [2.0, 2.1, 2.2, 2.3, 2.4]]})
            _write_json(vocal_activity, {"segments": [{"start_time": 2.0, "end_time": 2.5, "state": "vocal", "mean_confidence": 0.1}]})
            _write_json(candidates, {"melody_candidates": {"notes": []}})

            result = build_gap_attribution(
                expected_notes=[_note(2.05, 2.45, 60)],
                predicted_notes=[],
                f0_track_path=f0_track,
                vocal_activity_path=vocal_activity,
                pitch_contours_path=None,
                note_candidates_path=candidates,
                selected_melody_path=None,
                quantized_notes_path=None,
                score_ir_path=None,
                config=MidiMetricConfig(auto_octave_normalize=False),
            )

            self.assertEqual(result["top_lost_expected_notes"][0]["classification"], GAP_ATTR_RAW_F0_MISSING)
            self.assertEqual(result["top_lost_expected_notes"][0]["reason_codes"], [LOST_EXPECTED_RAW_F0_MISSING])

    def test_quantization_export_induced(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidates = root / "note_candidates.json"
            selected = root / "selected_melody.json"
            quantized = root / "quantized_notes.json"
            score_ir = root / "score_ir.json"
            _write_json(candidates, {"melody_candidates": {"notes": [_candidate("raw_1", 3.0, 3.4, 67)]}})
            _write_json(selected, {"selected_notes": [_selected("cand_1", 3.0, 3.4, 67)]})
            _write_json(quantized, {"quantizer_backend": "dp_v1", "fallback_used": False, "notes": [_quantized("qn_1", "cand_1", 3.0, 3.4, 67)]})
            _write_json(score_ir, {"notes": [_score_ir("n1", "qn_1", "cand_1", 3.0, 3.4, 67)]})

            result = build_gap_attribution(
                expected_notes=[_note(3.0, 3.4, 67)],
                predicted_notes=[],
                f0_track_path=None,
                vocal_activity_path=None,
                pitch_contours_path=None,
                note_candidates_path=candidates,
                selected_melody_path=selected,
                quantized_notes_path=quantized,
                score_ir_path=score_ir,
                config=MidiMetricConfig(auto_octave_normalize=False),
            )

            self.assertEqual(result["top_lost_expected_notes"][0]["classification"], GAP_ATTR_QUANTIZATION_EXPORT_INDUCED)
            self.assertEqual(result["top_lost_expected_notes"][0]["reason_codes"], [LOST_EXPECTED_QUANTIZATION_EXPORT_INDUCED])
            self.assertEqual(result["quantization_export"]["count_drop_stage"], "score_ir_to_predicted_midi")


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _note(start: float, end: float, pitch: int) -> NoteEvent:
    return NoteEvent(start=start, end=end, pitch=pitch)


def _candidate(candidate_id: str, start: float, end: float, pitch: int, *, confidence: float = 0.8) -> dict:
    return {
        "candidate_id": candidate_id,
        "start_time": start,
        "end_time": end,
        "pitch": _pitch_name(pitch),
        "confidence": confidence,
        "reason_codes": [],
    }


def _selected(candidate_id: str, start: float, end: float, pitch: int) -> dict:
    return {
        "candidate_id": candidate_id,
        "start_time_sec": start,
        "end_time_sec": end,
        "pitch_center_midi": pitch,
        "confidence": 0.8,
        "reason_codes": [],
    }


def _quantized(note_id: str, candidate_id: str, start: float, end: float, pitch: int) -> dict:
    return {
        "id": note_id,
        "source_candidate_id": candidate_id,
        "start_time_sec": start,
        "end_time_sec": end,
        "quantized_start_time_sec": start,
        "quantized_end_time_sec": end,
        "pitch_midi": pitch,
        "reason_codes": [],
    }


def _score_ir(note_id: str, qn_id: str, candidate_id: str, start: float, end: float, pitch: int) -> dict:
    return {
        "id": note_id,
        "quantized_note_id": qn_id,
        "source_candidate_id": candidate_id,
        "performance_start_time_sec": start,
        "performance_end_time_sec": end,
        "pitch_midi": pitch,
        "reason_codes": [],
    }


def _frame(time_sec: float, pitch: int, confidence: float, voiced: bool) -> dict:
    return {"time_sec": time_sec, "pitch_midi": pitch, "confidence": confidence, "voiced": voiced}


def _pitch_name(pitch: int) -> str:
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    return f"{names[pitch % 12]}{pitch // 12 - 1}"


if __name__ == "__main__":
    unittest.main()
