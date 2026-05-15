from __future__ import annotations

import unittest

from app.modules.pitch.note_candidate_builder import NoteCandidateBuilder
from app.modules.pitch.reason_codes import LOW_CONFIDENCE, TOO_UNSTABLE, UNCERTAIN


def _frame(
    time_sec: float,
    midi_float: float | None,
    *,
    confidence: float = 0.9,
    voiced: bool = True,
    frame_index: int | None = None,
) -> dict:
    payload = {
        "time_sec": time_sec,
        "midi_float": midi_float,
        "confidence": confidence,
        "voiced": voiced,
    }
    if frame_index is not None:
        payload["frame_index"] = frame_index
    return payload


class TestNoteCandidateBuilder(unittest.TestCase):
    def test_builds_candidate_from_stable_contour_when_raw_candidates_empty(self) -> None:
        f0_track = {
            "backend": "rmvpe",
            "source_stem": "vocals",
            "frames": [
                _frame(0.00, 60.02, frame_index=0),
                _frame(0.01, 60.04, frame_index=1),
                _frame(0.02, 60.01, frame_index=2),
                _frame(0.03, 60.03, frame_index=3),
            ],
        }
        pitch_contours = {
            "version": "pitch_contours_v1",
            "source_f0_track": "rmvpe",
            "contours": [
                {
                    "id": "pc_seed_1",
                    "start_time_sec": 0.0,
                    "end_time_sec": 0.04,
                    "duration_sec": 0.04,
                    "pitch_center_midi": 60.025,
                    "mean_confidence": 0.91,
                    "voiced_ratio": 1.0,
                    "stability": 0.96,
                    "frame_count": 4,
                    "frame_samples": [
                        {"time_sec": 0.00, "pitch_midi": 60.02, "confidence": 0.92, "voiced": True},
                        {"time_sec": 0.01, "pitch_midi": 60.04, "confidence": 0.91, "voiced": True},
                        {"time_sec": 0.02, "pitch_midi": 60.01, "confidence": 0.90, "voiced": True},
                        {"time_sec": 0.03, "pitch_midi": 60.03, "confidence": 0.91, "voiced": True},
                    ],
                }
            ],
        }

        result = NoteCandidateBuilder().build(
            f0_track=f0_track,
            pitch_contours=pitch_contours,
            raw_candidates={"melody_candidates": {"notes": []}},
        )

        notes = result["melody_candidates"]["notes"]
        self.assertEqual(len(notes), 1)
        note = notes[0]
        self.assertEqual(note["candidate_origin"], "note_candidate_builder.contour_seed")
        self.assertEqual(note["source_contour_ids"], ["pc_seed_1"])
        self.assertEqual(note["source_f0_frame_range"]["start_frame_index"], 0)
        self.assertEqual(note["source_f0_frame_range"]["end_frame_index"], 3)
        self.assertEqual(note["segmentation_evidence"]["strategy"], "pitch_contour_seed")
        self.assertTrue(note["candidate_id"].startswith("nc_contour_"))
        self.assertEqual(result["analysis_info"]["raw_candidates_empty"], True)

    def test_rejects_low_confidence_unstable_contour_with_reason_codes(self) -> None:
        f0_track = {
            "backend": "rmvpe",
            "frames": [
                _frame(0.00, 60.0, confidence=0.30, frame_index=0),
                _frame(0.01, 61.8, confidence=0.32, frame_index=1),
                _frame(0.02, 59.7, confidence=0.28, frame_index=2),
                _frame(0.03, 62.1, confidence=0.31, frame_index=3),
            ],
        }
        pitch_contours = {
            "version": "pitch_contours_v1",
            "source_f0_track": "rmvpe",
            "contours": [
                {
                    "id": "pc_reject_1",
                    "start_time_sec": 0.0,
                    "end_time_sec": 0.04,
                    "duration_sec": 0.04,
                    "pitch_center_midi": 60.8,
                    "mean_confidence": 0.30,
                    "voiced_ratio": 0.5,
                    "stability": 0.18,
                    "frame_count": 4,
                    "reason_codes": [LOW_CONFIDENCE, TOO_UNSTABLE],
                    "frame_samples": [
                        {"time_sec": 0.00, "pitch_midi": 60.0, "confidence": 0.30, "voiced": True},
                        {"time_sec": 0.01, "pitch_midi": 61.8, "confidence": 0.32, "voiced": True},
                        {"time_sec": 0.02, "pitch_midi": 59.7, "confidence": 0.28, "voiced": True},
                        {"time_sec": 0.03, "pitch_midi": 62.1, "confidence": 0.31, "voiced": True},
                    ],
                }
            ],
        }

        result = NoteCandidateBuilder().build(
            f0_track=f0_track,
            pitch_contours=pitch_contours,
            raw_candidates=None,
        )

        self.assertEqual(result["melody_candidates"]["notes"], [])
        rejected = result["analysis_info"]["rejected_candidates"]
        self.assertEqual(len(rejected), 1)
        self.assertIn(LOW_CONFIDENCE, rejected[0]["reason_codes"])
        self.assertIn(TOO_UNSTABLE, rejected[0]["reason_codes"])
        self.assertIn(UNCERTAIN, rejected[0]["reason_codes"])

    def test_same_input_produces_stable_candidate_id(self) -> None:
        f0_track = {
            "backend": "rmvpe",
            "frames": [
                _frame(1.00, 64.0, frame_index=100),
                _frame(1.01, 64.0, frame_index=101),
                _frame(1.02, 64.02, frame_index=102),
                _frame(1.03, 64.01, frame_index=103),
            ],
        }
        pitch_contours = {
            "version": "pitch_contours_v1",
            "source_f0_track": "rmvpe",
            "contours": [
                {
                    "id": "pc_stable_id",
                    "start_time_sec": 1.0,
                    "end_time_sec": 1.04,
                    "duration_sec": 0.04,
                    "pitch_center_midi": 64.01,
                    "mean_confidence": 0.95,
                    "voiced_ratio": 1.0,
                    "stability": 0.99,
                    "frame_count": 4,
                    "frame_samples": [
                        {"time_sec": 1.00, "pitch_midi": 64.0, "confidence": 0.95, "voiced": True},
                        {"time_sec": 1.01, "pitch_midi": 64.0, "confidence": 0.95, "voiced": True},
                        {"time_sec": 1.02, "pitch_midi": 64.02, "confidence": 0.94, "voiced": True},
                        {"time_sec": 1.03, "pitch_midi": 64.01, "confidence": 0.95, "voiced": True},
                    ],
                }
            ],
        }

        builder = NoteCandidateBuilder()
        first = builder.build(f0_track=f0_track, pitch_contours=pitch_contours, raw_candidates=None)
        second = builder.build(f0_track=f0_track, pitch_contours=pitch_contours, raw_candidates=None)

        first_note = first["melody_candidates"]["notes"][0]
        second_note = second["melody_candidates"]["notes"][0]
        self.assertEqual(first_note["candidate_id"], second_note["candidate_id"])
        self.assertEqual(first_note["source_f0_frame_range"], second_note["source_f0_frame_range"])


if __name__ == "__main__":
    unittest.main()
