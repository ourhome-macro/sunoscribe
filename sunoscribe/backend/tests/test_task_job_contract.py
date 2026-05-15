from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from app.models.enums import TaskStatus, TaskType
from app.services.task_manifest_service import TaskManifestService
from app.services.task_service import task_to_dict


class TestTaskJobContract(unittest.TestCase):
    def test_task_status_supports_cancelled(self) -> None:
        self.assertEqual(TaskStatus.CANCELLED.value, "cancelled")

    def test_task_type_supports_transcription(self) -> None:
        self.assertEqual(TaskType.TRANSCRIPTION.value, "transcription")

    def test_task_to_dict_exposes_transcription_and_failure_reason(self) -> None:
        now = datetime.now(timezone.utc)
        task = SimpleNamespace(
            id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            task_type="transcription",
            status="failed",
            progress=56,
            retry_count=0,
            max_retries=0,
            error_message="pitch_pipeline_failed:model_missing",
            input_payload={"transcription_target": "lead_vocal", "score_type": "staff", "key": "C Major"},
            result_payload={},
            queued_at=now,
            started_at=now,
            finished_at=now,
        )

        payload = task_to_dict(task)

        self.assertEqual(payload["transcription_target"], "lead_vocal")
        self.assertEqual(payload["failure_reason"], "pitch_pipeline_failed:model_missing")
        self.assertEqual(payload["status"], "failed")

    def test_manifest_service_writes_manifest_payload(self) -> None:
        now = datetime.now(timezone.utc)
        task = SimpleNamespace(
            id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            task_type="transcription",
            status="queued",
            progress=0,
            error_message=None,
            input_payload={"transcription_target": "lead_vocal"},
            result_payload={},
            queued_at=now,
            started_at=None,
            finished_at=None,
        )

        service = TaskManifestService()
        payload = service._build_manifest_payload(task=task, outputs=None, cleanup=None)

        self.assertEqual(payload["transcription_target"], "lead_vocal")
        self.assertEqual(payload["status"], "queued")
        self.assertIn("timeout_seconds", payload)


if __name__ == "__main__":
    unittest.main()
