from __future__ import annotations

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from app.models.enums import ScoreType
from app.models.lyrics import Lyrics
from app.models.score import Score
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


class TestScoreGenerationService(unittest.TestCase):
    def test_generate_score_runs_audio_analysis_and_persists_outputs(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4())
        project = SimpleNamespace(
            id=uuid.uuid4(),
            user_id=user.id,
            audio_path="/tmp/project-input.wav",
            status="processing",
            progress=5,
        )
        db = _FakeSession([project, None, None])
        analysis_result = SimpleNamespace(
            score_ir={
                "meta": {
                    "bpm": 120.0,
                    "key": "C Major",
                    "key_confidence": 0.9,
                    "duration_sec": 3.2,
                    "time_signature": "4/4",
                    "rhythm_type": "stable",
                    "total_measures": 1,
                    "has_anacrusis": False,
                    "analysis_info": {},
                },
                "notes": [
                    {
                        "id": "n000001",
                        "pitch": "C4",
                        "start_time": 0.0,
                        "end_time": 0.5,
                    }
                ],
                "measures": [{"measure_num": 1, "note_ids": ["n000001"]}],
            },
            lyrics_segments=[{"text": "hello", "start": 0.0, "end": 0.5}],
            warnings=["pitch-warning"],
            midi_path="data/projects/test/final_score.mid",
        )

        with patch("app.services.score_service._run_audio_analysis", return_value=analysis_result) as mocked_analysis:
            score = generate_or_regenerate_score(
                db,
                user=user,
                project_id=str(project.id),
                score_type=ScoreType.JIANPU,
                key="C Major",
            )

        mocked_analysis.assert_called_once_with(project)
        self.assertIsInstance(score, Score)
        self.assertEqual(score.score_type, "jianpu")
        self.assertEqual(score.key, "C Major")
        self.assertEqual(score.score_data["generated_by"], "audio_analysis_service")
        self.assertEqual(score.score_data["meta"]["project_id"], str(project.id))
        self.assertEqual(score.score_data["meta"]["requested_key"], "C Major")
        self.assertEqual(score.score_data["notes"][0]["pitch"], "C4")
        self.assertEqual(score.score_data["final_midi_path"], "data/projects/test/final_score.mid")
        lyrics_rows = [obj for obj in db.added if isinstance(obj, Lyrics)]
        self.assertEqual(len(lyrics_rows), 1)
        self.assertEqual(lyrics_rows[0].text, "hello")
        self.assertEqual(lyrics_rows[0].timeline, analysis_result.lyrics_segments)
        self.assertEqual(db.commit_count, 1)


if __name__ == "__main__":
    unittest.main()
