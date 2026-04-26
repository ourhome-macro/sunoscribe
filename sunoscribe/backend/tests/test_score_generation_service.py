from __future__ import annotations

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from app.models.enums import ProjectStatus, ScoreType
from app.models.lyrics import Lyrics
from app.models.score import Score
from app.services.audio_analysis_service import AudioAnalysisResult
from app.services.score_service import generate_or_regenerate_score


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.added = []
        self.commit_count = 0
        self.refreshed = []

    def execute(self, _stmt):
        return _ScalarResult(self._responses.pop(0))

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commit_count += 1

    def refresh(self, obj):
        self.refreshed.append(obj)


def _fake_analysis_result(*, project_id: str, lyrics_segments: list[dict] | None = None) -> AudioAnalysisResult:
    return AudioAnalysisResult(
        project_id=project_id,
        source_audio_path=f"data/projects/{project_id}/input/source.wav",
        normalized_audio_path=None,
        vocals_path=f"data/projects/{project_id}/separation/vocals.wav",
        accompaniment_path=f"data/projects/{project_id}/separation/accompaniment.wav",
        lyrics_segments=lyrics_segments or [],
        pitch_result={"meta": {"bpm": 120}},
        analysis_ir={"summary": "ok"},
        score_data={
            "bpm": 120,
            "key": "C Major",
            "time_signature": "4/4",
            "measures": [
                {
                    "measure_num": 1,
                    "notes": [
                        {
                            "pitch": "C4",
                            "duration_beats": 1.0,
                            "note_type": "quarter",
                        }
                    ],
                }
            ],
            "warnings": ["serializer_warning"],
        },
        score_ir={"meta": {"source_version": "test"}, "notes": [{"pitch": "C4"}]},
        baseline_alignment={},
        baseline_validator_warnings=[],
        refined_alignment=None,
        final_alignment={},
        alignment_source="baseline",
        alignment_accepted=True,
        refine_warnings=[],
        validator_warnings_before=[],
        validator_warnings_after=[],
        refine_debug=None,
        midi_path=f"data/projects/{project_id}/exports/final_score.mid",
        stem_paths={"vocals": f"data/projects/{project_id}/separation/vocals.wav"},
        semantic_audio={"source_stems": {}},
        warnings=["analysis_warning"],
    )


class TestScoreGenerationService(unittest.TestCase):
    def test_generate_score_uses_audio_analysis_and_persists_outputs(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4())
        project = SimpleNamespace(
            id=uuid.uuid4(),
            user_id=user.id,
            audio_path="/tmp/project-input.wav",
            status="processing",
            progress=5,
        )
        db = _FakeSession([project, None, None])
        analysis_result = _fake_analysis_result(
            project_id=str(project.id),
            lyrics_segments=[{"text": "hello", "start": 0.0, "end": 0.5}],
        )

        with patch("app.services.score_service._run_audio_analysis", return_value=analysis_result) as mocked_analysis:
            score = generate_or_regenerate_score(
                db,
                user=user,
                project_id=str(project.id),
                score_type=ScoreType.JIANPU,
                key="G Major",
            )

        mocked_analysis.assert_called_once_with(project)
        self.assertIsInstance(score, Score)
        self.assertEqual(score.score_type, "jianpu")
        self.assertEqual(score.key, "G Major")
        self.assertEqual(project.status, ProjectStatus.COMPLETED.value)
        self.assertEqual(project.progress, 100)
        self.assertEqual(score.score_data["generated_by"], "audio_analysis_service")
        self.assertEqual(score.score_data["meta"]["project_id"], str(project.id))
        self.assertEqual(score.score_data["meta"]["requested_key"], "G Major")
        self.assertEqual(score.score_data["measures"][0]["notes"][0]["pitch"], "C4")
        self.assertEqual(score.score_data["midi_path"], analysis_result.midi_path)
        self.assertEqual(score.score_data["final_midi_path"], analysis_result.midi_path)
        self.assertIn("serializer_warning", score.score_data["warnings"])
        self.assertIn("analysis_warning", score.score_data["warnings"])

        lyrics_rows = [obj for obj in db.added if isinstance(obj, Lyrics)]
        self.assertEqual(len(lyrics_rows), 1)
        self.assertEqual(lyrics_rows[0].text, "hello")
        self.assertEqual(lyrics_rows[0].timeline, analysis_result.lyrics_segments)
        self.assertEqual(db.commit_count, 1)

    def test_generate_score_without_audio_path_keeps_stub_fallback(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4())
        project = SimpleNamespace(id=uuid.uuid4(), user_id=user.id, audio_path=None, status="processing", progress=30)
        db = _FakeSession([project, None, None])

        with patch("app.services.score_service._run_audio_analysis") as mocked_analysis:
            score = generate_or_regenerate_score(
                db,
                user=user,
                project_id=str(project.id),
                score_type=ScoreType.STAFF,
                key="C Major",
            )

        mocked_analysis.assert_not_called()
        self.assertEqual(project.status, ProjectStatus.COMPLETED.value)
        self.assertEqual(project.progress, 100)
        self.assertEqual(score.score_data["generated_by"], "backend_stub")
        self.assertEqual(score.score_data["meta"]["score_type"], ScoreType.STAFF.value)


if __name__ == "__main__":
    unittest.main()
