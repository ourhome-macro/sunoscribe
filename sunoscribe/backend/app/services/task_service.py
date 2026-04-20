import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import ProjectStatus, TaskStatus, TaskType
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.utils.errors import NotFoundError, ValidationAppError


def create_score_generation_task(
    db: Session,
    *,
    user: User,
    project_id: str,
    score_type: str,
    key: str,
    max_retries: int = 2,
) -> Task:
    project_uuid = _parse_uuid(project_id, "project_id")
    project_stmt = select(Project).where(Project.id == project_uuid, Project.user_id == user.id)
    project = db.execute(project_stmt).scalar_one_or_none()
    if project is None:
        raise NotFoundError("project not found")

    task = Task(
        user_id=user.id,
        project_id=project.id,
        task_type=TaskType.SCORE_GENERATION.value,
        status=TaskStatus.QUEUED.value,
        progress=0,
        input_payload={"score_type": score_type, "key": key},
        result_payload={},
        retry_count=0,
        max_retries=max(0, int(max_retries)),
        queued_at=datetime.now(timezone.utc),
    )

    project.status = ProjectStatus.PROCESSING.value
    project.progress = 0

    db.add(project)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def get_task_status_by_id(db: Session, *, user: User, task_id: str) -> dict:
    task_uuid = _parse_uuid(task_id, "task_id")
    stmt = select(Task).where(Task.id == task_uuid, Task.user_id == user.id)
    task = db.execute(stmt).scalar_one_or_none()
    if task is None:
        raise NotFoundError("task not found")
    return _task_to_dict(task)


def retry_task(db: Session, *, user: User, task_id: str) -> Task:
    task_uuid = _parse_uuid(task_id, "task_id")
    stmt = select(Task).where(Task.id == task_uuid, Task.user_id == user.id)
    task = db.execute(stmt).scalar_one_or_none()
    if task is None:
        raise NotFoundError("task not found")

    if task.status != TaskStatus.FAILED.value:
        raise ValidationAppError("only failed task can be retried")

    if task.retry_count >= task.max_retries:
        raise ValidationAppError("retry count limit reached")

    task.retry_count += 1
    task.status = TaskStatus.QUEUED.value
    task.progress = 0
    task.error_message = None
    task.result_payload = {}
    task.started_at = None
    task.finished_at = None
    task.queued_at = datetime.now(timezone.utc)

    project = db.get(Project, task.project_id)
    if project is not None:
        project.status = ProjectStatus.PROCESSING.value
        project.progress = 0
        db.add(project)

    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def get_task_by_id(db: Session, *, task_id: str) -> Task | None:
    try:
        task_uuid = uuid.UUID(str(task_id))
    except (TypeError, ValueError):
        return None
    return db.get(Task, task_uuid)


def task_to_dict(task: Task) -> dict[str, Any]:
    return _task_to_dict(task)


def _task_to_dict(task: Task) -> dict[str, Any]:
    can_retry = task.status == TaskStatus.FAILED.value and task.retry_count < task.max_retries
    return {
        "task_id": task.id,
        "project_id": task.project_id,
        "task_type": task.task_type,
        "status": task.status,
        "progress": int(task.progress),
        "retry_count": int(task.retry_count),
        "max_retries": int(task.max_retries),
        "can_retry": bool(can_retry),
        "error_message": task.error_message,
        "result_payload": task.result_payload if isinstance(task.result_payload, dict) else {},
        "queued_at": task.queued_at,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
    }


def _parse_uuid(raw: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(raw))
    except (TypeError, ValueError) as exc:
        raise ValidationAppError(f"{field_name} must be a valid UUID") from exc
