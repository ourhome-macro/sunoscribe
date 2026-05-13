from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from app.models.artifact import Artifact
from app.models.lyrics import Lyrics
from app.models.score import Score
from app.models.score_revision import ScoreRevision
from app.models.user import User
from app.modules.agents.audio_analysis_agent import AudioAnalysisAgent
from app.modules.agents.types import AgentRevisionContext
from app.services.agent_workflow_service import AgentWorkflowService


def _build_revision() -> tuple[Score, ScoreRevision]:
    project_id = uuid.uuid4()
    score = Score(id=uuid.uuid4(), project_id=project_id, score_type="staff", key="C Major")
    revision = ScoreRevision(
        id=uuid.uuid4(),
        project_id=project_id,
        score_id=score.id,
        revision_number=1,
        revision_type="machine",
        score_type="staff",
        key="C Major",
        score_ir={
            "meta": {"bpm": 120.0, "bpm_confidence": 0.8, "rhythm_type": "stable", "time_signature": "4/4"},
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
                    "confidence": 0.92,
                },
                {
                    "id": "n2",
                    "pitch": "E4",
                    "pitch_midi": 64,
                    "start_time": 1.0,
                    "end_time": 2.0,
                    "duration_sec": 1.0,
                    "duration_beats": 2.0,
                    "measure_num": 1,
                    "beat_position": 3.0,
                    "confidence": 0.88,
                },
                {
                    "id": "n3",
                    "pitch": "G4",
                    "pitch_midi": 67,
                    "start_time": 2.0,
                    "end_time": 3.0,
                    "duration_sec": 1.0,
                    "duration_beats": 2.0,
                    "measure_num": 2,
                    "beat_position": 1.5,
                    "confidence": 0.86,
                },
            ],
            "form_sections": [
                {"id": "s1", "label": "Verse", "start_time": 0.0, "end_time": 2.0},
                {"id": "s2", "label": "Chorus", "start_time": 2.0, "end_time": 3.5},
            ],
            "warnings": [],
        },
        score_data={},
        patch_data={},
        revision_metadata={},
    )
    revision.score = score
    score.revisions = [revision]
    score.current_revision = revision
    score.current_revision_id = revision.id
    return score, revision


def _f0_track() -> dict:
    frames = []
    for index in range(80):
        time_sec = index * 0.025
        frames.append(
            {
                "time_sec": time_sec,
                "pitch_midi": 60.0 + (0.4 if (index // 4) % 2 else -0.4),
                "frequency_hz": 261.63,
                "confidence": 0.9,
                "voiced": True,
            }
        )
    for index in range(80, 120):
        time_sec = index * 0.025
        frames.append(
            {
                "time_sec": time_sec,
                "pitch_midi": 62.0 + (index - 80) * 0.08,
                "frequency_hz": 293.66,
                "confidence": 0.86,
                "voiced": True,
            }
        )
    return {"frames": frames, "vocal_activity": [{"state": "vocal", "start_time": 0.0, "end_time": 4.0}]}


class TestAudioAnalysisReport(unittest.TestCase):
    def test_audio_analysis_agent_generates_report_with_lyrics(self) -> None:
        _, revision = _build_revision()
        context = AgentRevisionContext(
            project_id=str(revision.project_id),
            revision_id=str(revision.id),
            score_ir=revision.score_ir,
            f0_track=_f0_track(),
            rhythm_grid={"bpm": 120.0, "beat_times": [0.0, 0.5, 1.0, 1.5, 2.0], "stability_score": 0.93},
        )

        report = AudioAnalysisAgent().run(
            context,
            lyrics={"text": "爱和希望\n孤独的夜", "timeline": [{"start": 0.0, "end": 2.0, "text": "爱和希望"}]},
        )

        self.assertEqual(report.revision_id, str(revision.id))
        self.assertTrue(report.pitch.available)
        self.assertEqual(report.range.lowest_pitch, "C4")
        self.assertTrue(report.expression.available)
        self.assertGreaterEqual(report.expression.vibrato_segment_count, 1)
        self.assertTrue(report.rhythm.available)
        self.assertTrue(report.lyrics.available)
        self.assertGreaterEqual(report.summary.evidence_count, 4)

    def test_audio_analysis_agent_marks_missing_lyrics_without_blocking(self) -> None:
        _, revision = _build_revision()
        context = AgentRevisionContext(
            project_id=str(revision.project_id),
            revision_id=str(revision.id),
            score_ir=revision.score_ir,
            f0_track=_f0_track(),
            rhythm_grid={"bpm": 120.0},
        )

        report = AudioAnalysisAgent().run(context, lyrics=None)

        self.assertEqual(report.status, "partial")
        self.assertFalse(report.lyrics.available)
        self.assertIn("missing_lyrics", report.warnings)
        self.assertTrue(report.pitch.available)

    def test_workflow_generates_revision_scoped_report_artifact(self) -> None:
        score, revision = _build_revision()
        user = User(id=uuid.uuid4(), username="agent", email="agent@example.com", password_hash="x")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            f0_path = root / "f0_track.json"
            rhythm_path = root / "rhythm_grid.json"
            f0_path.write_text(json.dumps(_f0_track()), encoding="utf-8")
            rhythm_path.write_text(json.dumps({"bpm": 120.0, "beat_times": [0.0, 0.5, 1.0, 1.5]}), encoding="utf-8")
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
                    artifact_type="rhythm_grid",
                    storage_path=str(rhythm_path),
                ),
            ]
            db = _FakeDb(lyrics=Lyrics(project_id=score.project_id, text="love light", timeline=[]))
            service = AgentWorkflowService(auto_configure_llm_client=False)
            service._list_revision_artifacts = lambda *_args, **_kwargs: artifacts

            with patch("app.services.agent_workflow_service.ProjectWorkspace", lambda project_id: _TempWorkspace(root, project_id)):
                with patch("app.services.agent_workflow_service.get_score_revision_by_id", return_value=revision):
                    report, artifact = service.run_audio_analysis(db, user=user, revision_id=str(revision.id))

            self.assertEqual(report.revision_id, str(revision.id))
            self.assertEqual(artifact.artifact_type, "audio_analysis_report")
            self.assertEqual(artifact.artifact_metadata["kind"], "audio_analysis_report")
            self.assertTrue(Path(str(artifact.storage_path)).exists())
            self.assertIs(score.current_revision, revision)
            self.assertEqual(db.commit_count, 1)


class _FakeScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return self


    def first(self):
        return None


class _FakeDb:
    def __init__(self, *, lyrics):
        self.lyrics = lyrics
        self.added = []
        self.commit_count = 0

    def execute(self, _stmt):
        return _FakeScalarResult(self.lyrics)

    def add(self, item):
        self.added.append(item)

    def commit(self):
        self.commit_count += 1

    def refresh(self, _item):
        return None


class _TempWorkspace:
    def __init__(self, root: Path, project_id: str) -> None:
        self.root = root
        self.project_id = project_id

    def ensure_structure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def revision_dir(self, revision_id: str) -> Path:
        return self.root / "revisions" / revision_id


if __name__ == "__main__":
    unittest.main()
