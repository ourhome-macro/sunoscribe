from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from pathlib import Path

from app.models.artifact import Artifact
from app.models.score import Score
from app.models.score_revision import ScoreRevision
from app.models.user import User
from app.services.agent_workflow_service import AgentWorkflowService


def _build_revision() -> tuple[Score, ScoreRevision]:
    score = Score(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        score_type="staff",
        key="C Major",
        score_data={"meta": {"bpm": 120.0}},
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
            "meta": {"time_signature": "4/4"},
            "notes": [
                {
                    "id": "n1",
                    "pitch": "C4",
                    "pitch_midi": 60,
                    "start_time": 0.0,
                    "end_time": 1.0,
                    "duration_sec": 1.0,
                    "duration_beats": 2.0,
                    "measure_num": 1,
                    "beat_position": 1.0,
                    "confidence": 0.9,
                    "lyric": None,
                }
            ],
            "measures": [
                {"measure_num": 1, "start_time": 0.0, "end_time": 2.0, "is_anacrusis": False, "note_ids": ["n1"]}
            ],
            "warnings": [],
        },
        score_data={"meta": {"bpm": 120.0}, "analysis_ir": {"version": "analysis_ir_v1"}},
        patch_data={},
        revision_metadata={},
    )
    revision.score = score
    score.revisions = [revision]
    score.current_revision = revision
    score.current_revision_id = revision.id
    return score, revision


class TestAgentWorkflowService(unittest.TestCase):
    def test_build_context_from_revision_reads_json_artifacts(self) -> None:
        score, revision = _build_revision()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            f0_path = root / "f0_track.json"
            note_candidates_path = root / "note_candidates.json"
            rhythm_grid_path = root / "rhythm_grid.json"
            f0_path.write_text(
                json.dumps({"frames": [], "vocal_activity": [{"state": "vocal", "start_time": 0.0, "end_time": 1.0}]}),
                encoding="utf-8",
            )
            note_candidates_path.write_text(json.dumps({"role": "melody_candidates"}), encoding="utf-8")
            rhythm_grid_path.write_text(json.dumps({"beats_per_bar": 4}), encoding="utf-8")

            artifacts = [
                Artifact(
                    id=uuid.uuid4(),
                    project_id=score.project_id,
                    score_id=score.id,
                    score_revision_id=revision.id,
                    artifact_type="f0_track",
                    storage_path=str(f0_path),
                ),
                Artifact(
                    id=uuid.uuid4(),
                    project_id=score.project_id,
                    score_id=score.id,
                    score_revision_id=revision.id,
                    artifact_type="note_candidates",
                    storage_path=str(note_candidates_path),
                ),
                Artifact(
                    id=uuid.uuid4(),
                    project_id=score.project_id,
                    score_id=score.id,
                    score_revision_id=revision.id,
                    artifact_type="rhythm_grid",
                    storage_path=str(rhythm_grid_path),
                ),
            ]

            context = AgentWorkflowService().build_context_from_revision(revision=revision, artifacts=artifacts)

        self.assertIsNotNone(context.f0_track)
        self.assertIsNotNone(context.note_candidates)
        self.assertIsNotNone(context.rhythm_grid)
        self.assertIsNotNone(context.vocal_activity)
        self.assertEqual(context.vocal_activity["segments"][0]["state"], "vocal")

    def test_apply_patch_to_revision_creates_new_revision(self) -> None:
        score, revision = _build_revision()
        user = User(id=uuid.uuid4(), username="agent", email="agent@example.com", password_hash="x")
        service = AgentWorkflowService()
        context = service.build_context_from_revision(revision=revision, artifacts=[])

        new_revision = service.apply_patch_to_revision(
            None,
            base_revision=revision,
            score=score,
            user=user,
            context=context,
            proposal={
                "base_revision_id": str(revision.id),
                "confidence": 0.91,
                "rationale": "raise the opening note",
                "operations": [{"op": "shift_octave", "note_id": "n1", "octaves": 1}],
            },
            commit=False,
        )

        self.assertEqual(new_revision.parent_revision_id, revision.id)
        self.assertEqual(new_revision.score_ir["notes"][0]["pitch_midi"], 72)
        self.assertEqual(score.current_revision, new_revision)


if __name__ == "__main__":
    unittest.main()
