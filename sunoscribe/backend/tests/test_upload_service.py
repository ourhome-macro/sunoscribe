from __future__ import annotations

import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.project_service import update_project_audio_path
from app.services.upload_service import (
    build_upload_object_key,
    build_upload_target_path,
    normalize_upload_backend,
    parse_uuid,
    validate_extension,
)
from app.utils.errors import UnsupportedFormatError, ValidationAppError


class TestUploadService(unittest.TestCase):
    def test_validate_audio_extension_ok(self) -> None:
        ext = validate_extension("song.mp3", "audio")
        self.assertEqual(ext, "mp3")

    def test_validate_video_extension_fail(self) -> None:
        with self.assertRaises(UnsupportedFormatError):
            validate_extension("movie.exe", "video")

    def test_build_upload_target_path(self) -> None:
        user_id = uuid.uuid4()
        project_id = uuid.uuid4()
        target = build_upload_target_path(
            uploads_root=Path("data/uploads"),
            user_id=user_id,
            project_id=project_id,
            original_filename="../a.wav",
        )
        expected = Path("data/uploads") / str(user_id) / str(project_id) / "a.wav"
        self.assertEqual(target, expected)

    def test_parse_uuid_invalid(self) -> None:
        with self.assertRaises(ValidationAppError):
            parse_uuid("bad-uuid", "project_id")

    def test_normalize_upload_backend(self) -> None:
        self.assertEqual(normalize_upload_backend("LOCAL"), "local")
        self.assertEqual(normalize_upload_backend("minio"), "minio")
        with self.assertRaises(ValidationAppError):
            normalize_upload_backend("oss")

    def test_build_upload_object_key(self) -> None:
        user_id = uuid.uuid4()
        project_id = uuid.uuid4()
        key = build_upload_object_key(
            user_id=user_id,
            project_id=project_id,
            original_filename="../audio.wav",
            base_path="uploads",
        )
        self.assertEqual(key, f"uploads/{user_id}/{project_id}/audio.wav")

    def test_update_project_audio_path(self) -> None:
        db = MagicMock()
        project = SimpleNamespace(audio_path=None)
        saved_path = "data/uploads/user/project/song.wav"

        updated = update_project_audio_path(db, project=project, audio_path=saved_path)

        self.assertIs(updated, project)
        self.assertEqual(project.audio_path, saved_path)
        db.add.assert_called_once_with(project)
        db.commit.assert_called_once()
        db.refresh.assert_called_once_with(project)


if __name__ == "__main__":
    unittest.main()
