from __future__ import annotations

import unittest
import uuid

from app.models.score import Score
from app.models.score_revision import ScoreRevision
from app.services.score_service import build_score_response


class TestScoreClientSummary(unittest.TestCase):
    def test_build_score_response_includes_note_confidence_without_storage_paths(self) -> None:
        score = Score(
            id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            score_type="staff",
            key="C Major",
            score_data={},
        )
        revision = ScoreRevision(
            id=uuid.uuid4(),
            project_id=score.project_id,
            score_id=score.id,
            revision_number=1,
            revision_type="machine",
            score_type="staff",
            key="C Major",
            score_ir={
                "notes": [
                    {
                        "id": "n1",
                        "pitch": "C4",
                        "start_tick": 0,
                        "duration_tick": 480,
                        "measure_num": 1,
                        "beat_position": 1.0,
                        "confidence": 0.9,
                        "reason_codes": [],
                        "source_candidate_id": "cand1",
                        "quantized_note_id": "qn1",
                    },
                    {
                        "id": "n2",
                        "pitch": "D4",
                        "start_tick": 480,
                        "duration_tick": 240,
                        "measure_num": 1,
                        "beat_position": 2.0,
                        "confidence": 0.4,
                        "reason_codes": ["high_quantize_error"],
                    },
                ]
            },
            score_data={},
        )
        revision.score = score
        score.current_revision = revision
        score.current_revision_id = revision.id
        score.revisions = [revision]

        response = build_score_response(score)
        current_summary = response["current_revision"]["client_summary"]

        self.assertEqual(current_summary["note_count"], 2)
        self.assertEqual(current_summary["uncertain_note_count"], 1)
        self.assertEqual(current_summary["low_confidence_note_count"], 1)
        self.assertEqual(current_summary["score_notes"][0]["confidence"], 0.9)
        self.assertEqual(current_summary["score_notes"][1]["reason_codes"], ["large_quantize_error", "low_confidence", "uncertain"])
        self.assertEqual(current_summary["score_notes"][0]["source_candidate_id"], "cand1")
        self.assertEqual(current_summary["score_notes"][0]["quantized_note_id"], "qn1")
        self.assertNotIn("storage_path", str(response))


if __name__ == "__main__":
    unittest.main()
