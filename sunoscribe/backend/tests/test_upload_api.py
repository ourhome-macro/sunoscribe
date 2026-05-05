from __future__ import annotations

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.upload import upload_audio_api
from app.utils.errors import NotFoundError


class TestUploadApi(unittest.IsolatedAsyncioTestCase):
    async def test_upload_audio_requires_owned_project_before_saving(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4())
        db = MagicMock()

        with patch("app.api.upload.get_project_by_id", side_effect=NotFoundError("项目不存在")), patch(
            "app.api.upload.save_upload_file",
            new=AsyncMock(),
        ) as mocked_save:
            with self.assertRaises(NotFoundError):
                await upload_audio_api(
                    project_id=str(uuid.uuid4()),
                    file=SimpleNamespace(filename="song.wav"),
                    db=db,
                    current_user=user,
                )

        mocked_save.assert_not_awaited()
        db.commit.assert_not_called()

    async def test_upload_audio_updates_project_media_path_after_save(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4())
        project = SimpleNamespace(id=uuid.uuid4(), audio_path=None)
        db = MagicMock()

        with patch("app.api.upload.get_project_by_id", return_value=project), patch(
            "app.api.upload.save_upload_file",
            new=AsyncMock(return_value=("data/uploads/project/source.wav", 123)),
        ) as mocked_save, patch(
            "app.api.upload._safe_probe_uploaded_media",
            return_value={"duration_sec": 1.0},
        ), patch(
            "app.api.upload.register_source_media_artifact",
            return_value=SimpleNamespace(id=uuid.uuid4()),
        ):
            response = await upload_audio_api(
                project_id=str(project.id),
                file=SimpleNamespace(filename="song.wav"),
                db=db,
                current_user=user,
            )

        mocked_save.assert_awaited_once()
        self.assertEqual(project.audio_path, "data/uploads/project/source.wav")
        db.add.assert_called_with(project)
        self.assertGreaterEqual(db.commit.call_count, 1)
        db.refresh.assert_called_once_with(project)
        self.assertEqual(response["data"]["file_path"], "data/uploads/project/source.wav")
        self.assertIsNotNone(response["data"]["artifact_id"])


if __name__ == "__main__":
    unittest.main()
