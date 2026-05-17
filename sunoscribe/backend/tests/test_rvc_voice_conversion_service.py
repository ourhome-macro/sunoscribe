from __future__ import annotations

import tempfile
import unittest
import uuid
from pathlib import Path

from app.models.artifact import Artifact
from app.models.score_revision import ScoreRevision
from app.modules.agents import RvcJobSpec
from app.services.rvc_voice_conversion_service import RvcVoiceConversionService
from app.utils.errors import ValidationAppError


class _FakeRvcClient:
    def __init__(self) -> None:
        self.calls = []

    def convert_voice(self, **kwargs):
        self.calls.append(kwargs)
        return b"RIFFfake-rvc", "audio/wav", {"status_code": 200}


class _NoopDb:
    def __init__(self) -> None:
        self.added = []

    def add(self, entity) -> None:
        self.added.append(entity)


class TestRvcVoiceConversionService(unittest.TestCase):
    def test_convert_records_rvc_vocal_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            vocal_path = Path(temp_dir) / "vocals.wav"
            vocal_path.write_bytes(b"RIFFvocals")
            project_id = uuid.uuid4()
            score_id = uuid.uuid4()
            revision = ScoreRevision(
                id=uuid.uuid4(),
                project_id=project_id,
                score_id=score_id,
                revision_number=1,
                revision_type="machine",
                score_type="staff",
                key="C Major",
                score_ir={},
                score_data={},
                patch_data={},
                revision_metadata={},
            )
            vocal_artifact = Artifact(
                id=uuid.uuid4(),
                project_id=project_id,
                score_id=score_id,
                score_revision_id=revision.id,
                artifact_type="vocals_stem",
                status="available",
                storage_path=str(vocal_path),
            )
            revision.artifacts = [vocal_artifact]
            spec = RvcJobSpec(
                mode="voice_conversion",
                project_id=str(project_id),
                revision_id=str(revision.id),
                vocal_stem_artifact_id=str(vocal_artifact.id),
                voice_model_id="voice-a",
                transpose_semitones=2,
            )
            client = _FakeRvcClient()
            db = _NoopDb()

            result, artifact = RvcVoiceConversionService(client=client).convert(db, revision=revision, spec=spec)

        self.assertEqual(result.mode, "voice_conversion")
        self.assertEqual(result.rvc_vocal_artifact_id, str(artifact.id))
        self.assertEqual(artifact.artifact_type, "rvc_vocal")
        self.assertEqual(artifact.artifact_metadata["score_guided"], False)
        self.assertEqual(client.calls[0]["voice_model_id"], "voice-a")
        self.assertEqual(db.added, [artifact])

    def test_convert_rejects_score_guided_spec(self) -> None:
        revision = ScoreRevision(
            id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            score_id=uuid.uuid4(),
            revision_number=1,
            revision_type="machine",
            score_type="staff",
            key="C Major",
            score_ir={},
            score_data={},
            patch_data={},
            revision_metadata={},
        )
        spec = RvcJobSpec(
            mode="score_guided",
            project_id=str(revision.project_id),
            revision_id=str(revision.id),
            voice_model_id="voice-a",
        )

        with self.assertRaisesRegex(ValidationAppError, "mode=voice_conversion"):
            RvcVoiceConversionService(client=_FakeRvcClient()).convert(_NoopDb(), revision=revision, spec=spec)


if __name__ == "__main__":
    unittest.main()
