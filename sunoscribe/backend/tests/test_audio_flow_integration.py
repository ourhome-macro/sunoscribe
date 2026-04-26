from __future__ import annotations

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.upload import upload_audio_api
from app.models.enums import ScoreType
from app.models.lyrics import Lyrics
from app.services.audio_analysis_service import AudioAnalysisResult
from app.services.score_service import export_score, generate_or_regenerate_score


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


def _analysis_result(project_id: str) -> AudioAnalysisResult:
    return AudioAnalysisResult(
        project_id=project_id,
        source_audio_path=f"data/projects/{project_id}/input/source.wav",
        normalized_audio_path=None,
        vocals_path=f"data/projects/{project_id}/separation/vocals.wav",
        accompaniment_path=f"data/projects/{project_id}/separation/accompaniment.wav",
        lyrics_segments=[{"id": "t1", "text": "hello", "start": 0.0, "end": 0.5}],
        pitch_result={"version": "test", "analysis_info": {"detector": "rmvpe"}},
        analysis_ir={"summary": "ok"},
        score_data={
            "bpm": 120,
            "key": "C Major",
            "time_signature": "4/4",
            "chord_timeline": [{"measure_num": 1, "symbol": "C", "root": "C", "quality": ""}],
            "form_sections": [{"id": "verse", "label": "verse", "measure_start": 1, "measure_end": 1}],
            "measures": [
                {
                    "measure_num": 1,
                    "notes": [
                        {
                            "id": "n1",
                            "pitch": "C4",
                            "start_time": 0.0,
                            "end_time": 0.5,
                            "duration_beats": 1.0,
                            "note_type": "quarter",
                            "confidence": 0.92,
                            "lyric": "hello",
                        }
                    ],
                }
            ],
        },
        score_ir={"meta": {"source_version": "test"}, "notes": [{"id": "n1", "pitch": "C4"}]},
        baseline_alignment={"alignments": [{"token_id": "t1", "note_ids": ["n1"]}]},
        baseline_validator_warnings=[],
        refined_alignment=None,
        final_alignment={"alignments": [{"token_id": "t1", "note_ids": ["n1"], "confidence": 0.9}]},
        alignment_source="baseline",
        alignment_accepted=True,
        refine_warnings=[],
        validator_warnings_before=[],
        validator_warnings_after=[],
        refine_debug=None,
        midi_path=f"data/projects/{project_id}/exports/final_score.mid",
        stem_paths={"vocals": f"data/projects/{project_id}/separation/vocals.wav"},
        semantic_audio={"source_stems": {"vocals": "vocals.wav"}},
        warnings=[],
    )


class TestAudioFlowIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_upload_analysis_alignment_and_exports_share_score_data(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4())
        project = SimpleNamespace(id=uuid.uuid4(), user_id=user.id, audio_path=None, status="pending", progress=0)
        upload_db = MagicMock()

        with patch("app.api.upload.get_project_by_id", return_value=project), patch(
            "app.api.upload.save_upload_file",
            new=AsyncMock(return_value=("data/uploads/user/project/song.wav", 2048)),
        ):
            upload_response = await upload_audio_api(
                project_id=str(project.id),
                file=SimpleNamespace(filename="song.wav"),
                db=upload_db,
                current_user=user,
            )

        self.assertEqual(upload_response["data"]["file_path"], "data/uploads/user/project/song.wav")
        self.assertEqual(project.audio_path, "data/uploads/user/project/song.wav")
        upload_db.commit.assert_called_once()

        score_db = _FakeSession([project, None, None])
        analysis_result = _analysis_result(str(project.id))
        with patch("app.services.score_service._run_audio_analysis", return_value=analysis_result):
            score = generate_or_regenerate_score(
                score_db,
                user=user,
                project_id=str(project.id),
                score_type=ScoreType.JIANPU,
                key="C Major",
            )

        self.assertEqual(score.score_data["pitch_result"]["analysis_info"]["detector"], "rmvpe")
        self.assertEqual(score.score_data["alignment"]["source"], "baseline")
        self.assertEqual(score.score_data["alignment"]["final"]["alignments"][0]["note_ids"], ["n1"])
        lyrics_rows = [obj for obj in score_db.added if isinstance(obj, Lyrics)]
        self.assertEqual(lyrics_rows[0].text, "hello")
        self.assertEqual(lyrics_rows[0].timeline, analysis_result.lyrics_segments)

        with patch("app.services.score_service.get_score_by_id", return_value=score):
            midi_bytes, midi_type, midi_name = export_score(
                score_db,
                user=user,
                score_id=str(score.id or uuid.uuid4()),
                export_format="midi",
            )
            xml_bytes, xml_type, xml_name = export_score(
                score_db,
                user=user,
                score_id=str(score.id or uuid.uuid4()),
                export_format="musicxml",
            )

        self.assertTrue(midi_bytes.startswith(b"MThd"))
        self.assertEqual(midi_type, "audio/midi")
        self.assertTrue(midi_name.endswith(".mid"))
        xml_text = xml_bytes.decode("utf-8", errors="ignore")
        self.assertIn("<score-partwise", xml_text)
        self.assertIn("<harmony>", xml_text)
        self.assertIn("<rehearsal>verse</rehearsal>", xml_text)
        self.assertIn("<text>hello</text>", xml_text)
        self.assertEqual(xml_type, "application/vnd.recordare.musicxml+xml")
        self.assertTrue(xml_name.endswith(".musicxml"))


if __name__ == "__main__":
    unittest.main()
