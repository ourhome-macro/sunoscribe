from __future__ import annotations

import json
import unittest
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from app.models.enums import ArtifactType
from app.services.score_revision_service import _register_analysis_artifacts
from app.services.workspace import ProjectWorkspace


class _FakeDB:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)


class TestTypedArtifactLineage(unittest.TestCase):
    def test_register_analysis_artifacts_includes_typed_pitch_artifacts(self) -> None:
        with TemporaryDirectory() as temp_dir:
            projects_root = Path(temp_dir) / "projects"
            project_id = uuid.uuid4()
            score_id = uuid.uuid4()
            revision_id = uuid.uuid4()
            workspace = ProjectWorkspace(project_id=str(project_id), projects_root=projects_root)
            workspace.ensure_structure()

            workspace.f0_track_path.write_text(json.dumps({"frames": [], "vocal_activity": []}), encoding="utf-8")
            workspace.note_candidates_path.write_text(
                json.dumps({"melody_candidates": {"notes": []}, "harmony_candidates": {"notes": []}}),
                encoding="utf-8",
            )
            workspace.rhythm_grid_path.write_text(json.dumps({"beats_per_bar": 4, "beat_times": [0.0]}), encoding="utf-8")
            workspace.pitch_result_path.write_text(json.dumps({"analysis_info": {"detector": "rmvpe"}}), encoding="utf-8")
            workspace.analysis_ir_path.write_text(json.dumps({"version": "analysis_ir_v1"}), encoding="utf-8")
            workspace.score_ir_path.write_text(json.dumps({"notes": [{"id": "n1"}]}), encoding="utf-8")
            workspace.lyrics_segments_path.write_text(json.dumps([]), encoding="utf-8")
            workspace.baseline_alignment_path.write_text(json.dumps({}), encoding="utf-8")
            workspace.final_alignment_path.write_text(json.dumps({}), encoding="utf-8")

            analysis_result = SimpleNamespace(
                source_audio_path=str(workspace.input_dir / "source.wav"),
                normalized_audio_path=str(workspace.normalized_audio_path),
                vocals_path=str(workspace.vocals_path),
                accompaniment_path=str(workspace.accompaniment_path),
            )

            db = _FakeDB()
            project = SimpleNamespace(id=project_id)
            score = SimpleNamespace(id=score_id)
            revision = SimpleNamespace(id=revision_id)

            with patch("app.services.score_revision_service.ProjectWorkspace", return_value=workspace):
                _register_analysis_artifacts(
                    db,
                    project=project,
                    score=score,
                    revision=revision,
                    analysis_result=analysis_result,
                    task_id=None,
                )

            artifact_types = {getattr(artifact, "artifact_type", None) for artifact in db.added}
            self.assertIn(ArtifactType.F0_TRACK.value, artifact_types)
            self.assertIn(ArtifactType.NOTE_CANDIDATES.value, artifact_types)
            self.assertIn(ArtifactType.RHYTHM_GRID.value, artifact_types)
            for artifact in db.added:
                storage_path = Path(str(getattr(artifact, "storage_path", "")))
                self.assertIn(str(revision_id), str(storage_path))
                self.assertTrue(storage_path.exists())
                self.assertIn("source_workspace_path", getattr(artifact, "artifact_metadata", {}))


if __name__ == "__main__":
    unittest.main()
