from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.score_service import export_score
from app.utils.errors import ValidationAppError


class TestScoreExportService(unittest.TestCase):
    def test_export_midi_prefers_existing_workspace_artifact(self) -> None:
        project_id = "test_export_project_001"
        midi_path = Path("data/projects") / project_id / "exports" / "final_score.mid"
        midi_path.parent.mkdir(parents=True, exist_ok=True)
        expected = b"MThd-test"
        midi_path.write_bytes(expected)

        fake_score = SimpleNamespace(id="score-1", project_id=project_id, score_data={})
        db = MagicMock()

        try:
            with patch("app.services.score_service.get_score_by_id", return_value=fake_score):
                content, media_type, filename = export_score(
                    db,
                    user=SimpleNamespace(),
                    score_id="dummy",
                    export_format="midi",
                )
        finally:
            shutil.rmtree(Path("data/projects") / project_id, ignore_errors=True)

        self.assertEqual(content, expected)
        self.assertEqual(media_type, "audio/midi")
        self.assertTrue(str(filename).endswith(".mid"))

    def test_export_midi_can_generate_from_score_data_measures(self) -> None:
        fake_score = SimpleNamespace(
            id="score-2",
            project_id="test_export_project_002",
            score_data={
                "bpm": 120,
                "measures": [
                    {
                        "measure_num": 1,
                        "notes": [
                            {
                                "pitch": "C4",
                                "start_time": 0.0,
                                "end_time": 0.5,
                                "duration_beats": 1.0,
                                "note_type": "quarter",
                                "confidence": 0.9,
                            }
                        ],
                    }
                ],
            },
        )
        db = MagicMock()
        with patch("app.services.score_service.get_score_by_id", return_value=fake_score):
            content, media_type, filename = export_score(
                db,
                user=SimpleNamespace(),
                score_id="dummy",
                export_format="midi",
            )

        self.assertIsInstance(content, (bytes, bytearray))
        self.assertGreater(len(content), 0)
        self.assertEqual(media_type, "audio/midi")
        self.assertTrue(str(filename).endswith(".mid"))

    def test_export_midi_without_artifact_or_measures_raises(self) -> None:
        fake_score = SimpleNamespace(id="score-3", project_id="test_export_project_003", score_data={"meta": {}})
        db = MagicMock()
        with patch("app.services.score_service.get_score_by_id", return_value=fake_score):
            with self.assertRaises(ValidationAppError):
                export_score(
                    db,
                    user=SimpleNamespace(),
                    score_id="dummy",
                    export_format="midi",
                )

    def test_export_midi_ignores_score_data_path_outside_workspace(self) -> None:
        external_dir = tempfile.TemporaryDirectory()
        external_path = Path(external_dir.name) / "outside.mid"
        external_path.write_bytes(b"MThd-outside")

        fake_score = SimpleNamespace(
            id="score-escape",
            project_id="test_export_project_006",
            score_data={"midi_path": str(external_path)},
        )
        db = MagicMock()

        try:
            with patch("app.services.score_service.get_score_by_id", return_value=fake_score):
                with self.assertRaises(ValidationAppError):
                    export_score(
                        db,
                        user=SimpleNamespace(),
                        score_id="dummy",
                        export_format="midi",
                    )
        finally:
            external_dir.cleanup()

    def test_export_musicxml_generated_from_measures(self) -> None:
        fake_score = SimpleNamespace(
            id="score-4",
            project_id="test_export_project_004",
            key="C Major",
            score_data={
                "meta": {"bpm": 100, "key": "C Major", "time_signature": "4/4"},
                "measures": [
                    {
                        "measure_num": 1,
                        "notes": [
                            {
                                "pitch": "C4",
                                "start_time": 0.0,
                                "end_time": 0.5,
                                "duration_beats": 1.0,
                                "note_type": "quarter",
                                "confidence": 0.9,
                            }
                        ],
                    }
                ],
            },
        )
        db = MagicMock()
        with patch("app.services.score_service.get_score_by_id", return_value=fake_score):
            content, media_type, filename = export_score(
                db,
                user=SimpleNamespace(),
                score_id="dummy",
                export_format="musicxml",
            )

        text = content.decode("utf-8", errors="ignore")
        self.assertIn("<score-partwise", text)
        self.assertIn("<measure", text)
        self.assertEqual(media_type, "application/vnd.recordare.musicxml+xml")
        self.assertTrue(str(filename).endswith(".musicxml"))

    def test_export_pdf_generates_real_pdf_bytes(self) -> None:
        fake_score = SimpleNamespace(
            id="score-5",
            project_id="test_export_project_005",
            key="C Major",
            score_data={"meta": {"bpm": 120, "key": "C Major"}, "measures": []},
        )
        db = MagicMock()
        with patch("app.services.score_service.get_score_by_id", return_value=fake_score):
            content, media_type, filename = export_score(
                db,
                user=SimpleNamespace(),
                score_id="dummy",
                export_format="pdf",
            )

        self.assertTrue(content.startswith(b"%PDF-1.4"))
        self.assertEqual(media_type, "application/pdf")
        self.assertTrue(str(filename).endswith(".pdf"))


if __name__ == "__main__":
    unittest.main()
