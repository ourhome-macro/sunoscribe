from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.modules.benchmark.gap_attribution import build_gap_attribution
from app.modules.benchmark.midi_metrics import MidiMetricConfig, NoteEvent
from app.modules.benchmark.reason_codes import (
    GAP_ATTR_CANDIDATE_EXISTS_SELECTOR_REMOVED,
    GAP_ATTR_F0_EXISTS_NO_CANDIDATE,
    GAP_ATTR_QUANTIZATION_EXPORT_INDUCED,
    GAP_ATTR_RAW_F0_MISSING,
    LOST_EXPECTED_CANDIDATE_EXISTS_SELECTOR_REMOVED,
    LOST_EXPECTED_F0_EXISTS_NO_CANDIDATE,
    LOST_EXPECTED_QUANTIZATION_EXPORT_INDUCED,
    LOST_EXPECTED_RAW_F0_MISSING,
    DELETED_CANDIDATE_SELECTOR_REMOVED,
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
