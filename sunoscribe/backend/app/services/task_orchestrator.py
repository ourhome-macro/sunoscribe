from __future__ import annotations

import logging
import queue
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import or_, select

from app.config import settings
from app.database import SessionLocal
from app.models.enums import ProjectStatus, ScoreType, TaskStatus, TaskType
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.services.score_service import generate_or_regenerate_score
from app.services.task_manifest_service import TaskManifestService


logger = logging.getLogger(__name__)


class TaskOrchestrator:
    def __init__(self, worker_count: int = 1) -> None:
        self.worker_count = max(1, int(worker_count))
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._threads: list[threading.Thread] = []
        self._running = False
        self._lock = threading.Lock()
        self._manifest_service = TaskManifestService()

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            self._threads = []

        try:
            self._recover_pending_tasks()
        except Exception:
            with self._lock:
                self._running = False
            raise

        with self._lock:
            for index in range(self.worker_count):
                worker = threading.Thread(target=self._worker_loop, name=f"task-worker-{index}", daemon=True)
                worker.start()
                self._threads.append(worker)

    def stop(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._running = False
            for _ in self._threads:
                self._queue.put(None)

        for worker in self._threads:
            worker.join(timeout=2)
        self._threads = []

    def enqueue(self, task_id: str) -> None:
        self._queue.put(str(task_id))

    def _recover_pending_tasks(self) -> None:
        with SessionLocal() as db:
            now = datetime.now(timezone.utc)
            stale_before = now - timedelta(minutes=settings.task_stale_after_minutes)

            stale_running = (
                db.execute(
                    select(Task)
                    .where(
                        Task.status == TaskStatus.RUNNING.value,
                        or_(Task.started_at.is_(None), Task.started_at < stale_before),
                    )
                    .with_for_update(skip_locked=True)
                )
                .scalars()
                .all()
            )
            for task in stale_running:
                task.status = TaskStatus.FAILED.value
                task.progress = min(99, max(0, int(task.progress)))
                task.error_message = "task_timeout_exceeded"
                task.finished_at = now
                db.add(task)

                project = db.get(Project, task.project_id)
                if project is not None:
                    project.status = ProjectStatus.FAILED.value
                    project.progress = min(99, max(0, int(project.progress)))
                    db.add(project)

            if stale_running:
                db.commit()
                for task in stale_running:
                    cleanup = self._manifest_service.cleanup_runtime(
                        project_id=str(task.project_id),
                        task_id=str(task.id),
                        reason="task_timeout_exceeded",
                    )
                    self._manifest_service.write_manifest(task=task, cleanup=cleanup)

            pending_ids = db.execute(
                select(Task.id).where(Task.status.in_([TaskStatus.QUEUED.value, TaskStatus.RETRYING.value]))
            ).scalars().all()

        for task_id in pending_ids:
            self.enqueue(str(task_id))

        if pending_ids:
            logger.info("Recovered %s pending task(s) on startup", len(pending_ids))

    def _worker_loop(self) -> None:
        while True:
            task_id = self._queue.get()
            try:
                if task_id is None:
                    return
                try:
                    self._process_task(task_id)
                except Exception:
                    logger.exception("Unexpected failure while processing task %s", task_id)
            finally:
                self._queue.task_done()

    def _process_task(self, task_id: str) -> None:
        task_uuid = self._parse_task_uuid(task_id)
        if task_uuid is None:
            return

        if not self._claim_task(task_uuid):
            return

        try:
            result_payload = self._execute_task(task_uuid)
        except Exception as exc:
            with SessionLocal() as db:
                task = db.get(Task, task_uuid)
                if task is None:
                    return
                if task.status == TaskStatus.CANCELLED.value:
                    cleanup = self._manifest_service.cleanup_runtime(
                        project_id=str(task.project_id),
                        task_id=str(task.id),
                        reason="cancelled",
                    )
                    self._manifest_service.write_manifest(task=task, cleanup=cleanup)
                    db.commit()
                    return
                task.status = TaskStatus.FAILED.value
                task.progress = min(99, max(0, int(task.progress)))
                task.error_message = str(exc)[:1000]
                task.finished_at = datetime.now(timezone.utc)
                db.add(task)

                project = db.get(Project, task.project_id)
                if project is not None:
                    project.status = ProjectStatus.FAILED.value
                    project.progress = min(99, max(0, int(project.progress)))
                    db.add(project)

                db.commit()
                cleanup = self._manifest_service.cleanup_runtime(
                    project_id=str(task.project_id),
                    task_id=str(task.id),
                    reason="failed",
                )
                self._manifest_service.write_manifest(task=task, cleanup=cleanup)
            return

        with SessionLocal() as db:
            task = db.get(Task, task_uuid)
            if task is None:
                return
            if task.status == TaskStatus.CANCELLED.value:
                cleanup = self._manifest_service.cleanup_runtime(
                    project_id=str(task.project_id),
                    task_id=str(task.id),
                    reason="cancelled",
                )
                self._manifest_service.write_manifest(task=task, outputs=result_payload, cleanup=cleanup)
                db.commit()
                return
            task.status = TaskStatus.SUCCEEDED.value
            task.progress = 100
            task.result_payload = result_payload
            task.error_message = None
            task.finished_at = datetime.now(timezone.utc)
            db.add(task)

            project = db.get(Project, task.project_id)
            if project is not None:
                project.status = ProjectStatus.COMPLETED.value
                project.progress = 100
                db.add(project)

            db.commit()
            cleanup = self._manifest_service.cleanup_runtime(
                project_id=str(task.project_id),
                task_id=str(task.id),
                reason="succeeded",
            )
            self._manifest_service.write_manifest(task=task, outputs=result_payload, cleanup=cleanup)

    def _execute_task(self, task_uuid: uuid.UUID) -> dict[str, Any]:
        with SessionLocal() as db:
            task = db.get(Task, task_uuid)
            if task is None:
                raise RuntimeError("task not found")

            if task.status == TaskStatus.CANCELLED.value:
                raise RuntimeError("task cancelled before execution")

            if task.task_type not in {TaskType.TRANSCRIPTION.value, TaskType.SCORE_GENERATION.value}:
                raise RuntimeError(f"unsupported task_type: {task.task_type}")

            project = db.get(Project, task.project_id)
            user = db.get(User, task.user_id)
            if project is None:
                raise RuntimeError("project not found")
            if user is None:
                raise RuntimeError("user not found")

            payload = task.input_payload if isinstance(task.input_payload, dict) else {}
            transcription_target = str(payload.get("transcription_target") or "lead_vocal")
            raw_score_type = str(payload.get("score_type") or ScoreType.JIANPU.value)
            raw_key = str(payload.get("key") or "C Major")
            if transcription_target != "lead_vocal":
                raise RuntimeError(f"unsupported transcription_target: {transcription_target}")

            try:
                score_type = ScoreType(raw_score_type)
            except ValueError as exc:
                raise RuntimeError(f"invalid score_type: {raw_score_type}") from exc

            task.progress = max(30, int(task.progress))
            db.add(task)
            db.commit()

            score = generate_or_regenerate_score(
                db,
                user=user,
                project_id=str(project.id),
                score_type=score_type,
                key=raw_key,
                task_id=str(task.id),
            )

            task.progress = 90
            db.add(task)
            db.commit()

            return {
                "task_id": str(task.id),
                "score_id": str(score.id),
                "project_id": str(project.id),
                "transcription_target": transcription_target,
                "score_type": score.score_type,
                "key": score.key,
                "status": TaskStatus.SUCCEEDED.value,
                "revision_id": str(score.current_revision_id) if score.current_revision_id else None,
                "current_revision_id": str(score.current_revision_id) if score.current_revision_id else None,
            }

    def _claim_task(self, task_uuid: uuid.UUID) -> bool:
        with SessionLocal() as db:
            task = (
                db.execute(
                    select(Task)
                    .where(
                        Task.id == task_uuid,
                        Task.status.in_([TaskStatus.QUEUED.value, TaskStatus.RETRYING.value]),
                    )
                    .with_for_update(skip_locked=True)
                )
                .scalars()
                .one_or_none()
            )
            if task is None:
                return False

            task.status = TaskStatus.RUNNING.value
            task.progress = max(5, int(task.progress))
            task.error_message = None
            task.started_at = datetime.now(timezone.utc)
            task.finished_at = None

            project = db.get(Project, task.project_id)
            if project is not None:
                project.status = ProjectStatus.PROCESSING.value
                project.progress = max(5, int(project.progress))
                db.add(project)

            db.add(task)
            db.commit()
            self._manifest_service.write_manifest(task=task)
            return True

    @staticmethod
    def _parse_task_uuid(raw: str) -> uuid.UUID | None:
        try:
            return uuid.UUID(str(raw))
        except (TypeError, ValueError):
            return None


task_orchestrator = TaskOrchestrator(worker_count=settings.task_worker_count)
