import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.artifact import Artifact
from app.models.enums import ProjectStatus, TaskStatus, TaskType
from app.models.project import Project
from app.models.score import Score
from app.models.score_revision import ScoreRevision
from app.models.task import Task
from app.models.user import User
from app.utils.errors import NotFoundError, ValidationAppError


DEFAULT_TRANSCRIPTION_TARGET = "lead_vocal"


def create_transcription_task(
    db: Session,
    *,
    user: User,
    project_id: str,
    score_type: str,
    key: str,
    transcription_target: str = DEFAULT_TRANSCRIPTION_TARGET,
    max_retries: int = 0,
) -> Task:
    project_uuid = _parse_uuid(project_id, "project_id")
    project_stmt = select(Project).where(Project.id == project_uuid, Project.user_id == user.id)
    project = db.execute(project_stmt).scalar_one_or_none()
    if project is None:
        raise NotFoundError("project not found")
    if str(transcription_target).strip() != DEFAULT_TRANSCRIPTION_TARGET:
        raise ValidationAppError("only lead_vocal transcription jobs are supported in the MVP")

    task = Task(
        user_id=user.id,
        project_id=project.id,
        task_type=TaskType.TRANSCRIPTION.value,
        status=TaskStatus.QUEUED.value,
        progress=0,
        input_payload={
            "transcription_target": DEFAULT_TRANSCRIPTION_TARGET,
            "score_type": str(score_type),
            "key": str(key),
        },
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


def create_score_generation_task(
    db: Session,
    *,
    user: User,
    project_id: str,
    score_type: str,
    key: str,
    max_retries: int = 0,
) -> Task:
    return create_transcription_task(
        db,
        user=user,
        project_id=project_id,
        score_type=score_type,
        key=key,
        transcription_target=DEFAULT_TRANSCRIPTION_TARGET,
        max_retries=max_retries,
    )


def get_task_status_by_id(db: Session, *, user: User, task_id: str) -> dict:
    task_uuid = _parse_uuid(task_id, "task_id")
    stmt = select(Task).where(Task.id == task_uuid, Task.user_id == user.id)
    task = db.execute(stmt).scalar_one_or_none()
    if task is None:
        raise NotFoundError("task not found")
    return _task_to_dict(task)


def get_task_outputs_by_id(db: Session, *, user: User, task_id: str) -> dict[str, Any]:
    task_uuid = _parse_uuid(task_id, "task_id")
    stmt = select(Task).where(Task.id == task_uuid, Task.user_id == user.id)
    task = db.execute(stmt).scalar_one_or_none()
    if task is None:
        raise NotFoundError("task not found")

    result_payload = task.result_payload if isinstance(task.result_payload, dict) else {}
    revision = _resolve_task_revision(db, task=task, result_payload=result_payload)
    artifacts = _list_task_artifacts(db, task=task, revision=revision)

    return {
        "task": _task_to_dict(task),
        "score": _serialize_score(revision.score if revision is not None else None),
        "revision": _serialize_revision(revision),
        "artifacts": [_serialize_artifact(artifact) for artifact in artifacts],
    }


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


def cancel_task(db: Session, *, user: User, task_id: str) -> Task:
    task_uuid = _parse_uuid(task_id, "task_id")
    stmt = select(Task).where(Task.id == task_uuid, Task.user_id == user.id)
    task = db.execute(stmt).scalar_one_or_none()
    if task is None:
        raise NotFoundError("task not found")

    if task.status in {TaskStatus.SUCCEEDED.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value}:
        raise ValidationAppError("only queued or running task can be cancelled")

    task.status = TaskStatus.CANCELLED.value
    task.error_message = "cancelled_by_user"
    task.finished_at = datetime.now(timezone.utc)
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
    input_payload = task.input_payload if isinstance(task.input_payload, dict) else {}
    result_payload = task.result_payload if isinstance(task.result_payload, dict) else {}
    return {
        "task_id": task.id,
        "project_id": task.project_id,
        "task_type": task.task_type,
        "transcription_target": str(input_payload.get("transcription_target") or DEFAULT_TRANSCRIPTION_TARGET),
        "status": task.status,
        "progress": int(task.progress),
        "retry_count": int(task.retry_count),
        "max_retries": int(task.max_retries),
        "can_retry": bool(can_retry),
        "failure_reason": task.error_message,
        "error_message": task.error_message,
        "result_payload": result_payload,
        "queued_at": task.queued_at,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
    }


def _resolve_task_revision(db: Session, *, task: Task, result_payload: dict[str, Any]) -> ScoreRevision | None:
    revision_id = result_payload.get("current_revision_id") or result_payload.get("revision_id")
    if revision_id:
        try:
            revision_uuid = uuid.UUID(str(revision_id))
        except (TypeError, ValueError):
            revision_uuid = None
        if revision_uuid is not None:
            revision = db.get(ScoreRevision, revision_uuid)
            if revision is not None:
                return revision

    score_id = result_payload.get("score_id")
    if not score_id:
        return None
    try:
        score_uuid = uuid.UUID(str(score_id))
    except (TypeError, ValueError):
        return None
    score = db.get(Score, score_uuid)
    return score.current_revision if score is not None else None


def _list_task_artifacts(db: Session, *, task: Task, revision: ScoreRevision | None) -> list[Artifact]:
    stmt = select(Artifact).where(Artifact.project_id == task.project_id)
    if revision is not None:
        stmt = stmt.where(
            (Artifact.task_id == task.id) | (Artifact.score_revision_id == revision.id)
        )
    else:
        stmt = stmt.where(Artifact.task_id == task.id)
    stmt = stmt.order_by(Artifact.created_at.asc())
    return list(db.execute(stmt).scalars().all())


def _serialize_score(score: Score | None) -> dict[str, Any] | None:
    if score is None:
        return None
    return {
        "score_id": str(score.id),
        "project_id": str(score.project_id),
        "score_type": str(score.score_type),
        "key": str(score.key),
        "current_revision_id": str(score.current_revision_id) if score.current_revision_id else None,
    }


def _serialize_revision(revision: ScoreRevision | None) -> dict[str, Any] | None:
    if revision is None:
        return None
    return {
        "revision_id": str(revision.id),
        "score_id": str(revision.score_id),
        "project_id": str(revision.project_id),
        "revision_number": int(revision.revision_number),
        "revision_type": str(revision.revision_type),
        "score_type": str(revision.score_type),
        "key": str(revision.key),
        "created_at": revision.created_at.isoformat() if revision.created_at else None,
        "updated_at": revision.updated_at.isoformat() if revision.updated_at else None,
    }


def _serialize_artifact(artifact: Artifact) -> dict[str, Any]:
    return {
        "artifact_id": str(artifact.id),
        "artifact_type": str(artifact.artifact_type),
        "status": str(artifact.status),
        "score_id": str(artifact.score_id) if artifact.score_id else None,
        "score_revision_id": str(artifact.score_revision_id) if artifact.score_revision_id else None,
        "task_id": str(artifact.task_id) if artifact.task_id else None,
        "storage_path": artifact.storage_path,
        "filename": artifact.filename,
        "mime_type": artifact.mime_type,
        "error_message": artifact.error_message,
        "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
        "updated_at": artifact.updated_at.isoformat() if artifact.updated_at else None,
    }


def _parse_uuid(raw: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(raw))
    except (TypeError, ValueError) as exc:
        raise ValidationAppError(f"{field_name} must be a valid UUID") from exc
