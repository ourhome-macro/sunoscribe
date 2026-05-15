from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import settings
from app.models.task import Task
from app.services.workspace import ProjectWorkspace


class TaskManifestService:
    def write_manifest(
        self,
        *,
        task: Task,
        outputs: dict[str, Any] | None = None,
        cleanup: dict[str, Any] | None = None,
    ) -> Path:
        workspace = ProjectWorkspace(project_id=str(task.project_id))
        workspace.ensure_structure()
        manifest_path = workspace.job_manifest_path(str(task.id))
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(
                self._build_manifest_payload(task=task, outputs=outputs, cleanup=cleanup),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return manifest_path

    def cleanup_runtime(self, *, project_id: str, task_id: str, reason: str) -> dict[str, Any]:
        workspace = ProjectWorkspace(project_id=str(project_id))
        workspace.ensure_structure()
        runtime_dir = workspace.job_runtime_dir(str(task_id))
        existed = runtime_dir.exists()
        if existed:
            shutil.rmtree(runtime_dir, ignore_errors=True)
        return {
            "cleanup_reason": str(reason),
            "runtime_dir": str(runtime_dir),
            "runtime_removed": bool(existed),
            "cleaned_at": datetime.utcnow().isoformat() + "Z",
        }

    def _build_manifest_payload(
        self,
        *,
        task: Task,
        outputs: dict[str, Any] | None,
        cleanup: dict[str, Any] | None,
    ) -> dict[str, Any]:
        input_payload = task.input_payload if isinstance(task.input_payload, dict) else {}
        result_payload = task.result_payload if isinstance(task.result_payload, dict) else {}
        resolved_outputs = outputs if isinstance(outputs, dict) else result_payload
        return {
            "task_id": str(task.id),
            "project_id": str(task.project_id),
            "user_id": str(task.user_id),
            "task_type": str(task.task_type),
            "transcription_target": str(input_payload.get("transcription_target") or "lead_vocal"),
            "status": str(task.status),
            "progress": int(task.progress),
            "failure_reason": task.error_message,
            "input_payload": input_payload,
            "result_payload": result_payload,
            "outputs": resolved_outputs,
            "timeout_seconds": int(settings.task_timeout_seconds),
            "queued_at": _isoformat(task.queued_at),
            "started_at": _isoformat(task.started_at),
            "finished_at": _isoformat(task.finished_at),
            "cleanup": cleanup or {},
        }


def _isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()
