import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.user import User
from app.utils.errors import NotFoundError, ValidationAppError


def get_task_status_by_id(db: Session, *, user: User, task_id: str) -> dict:
    task_uuid = _parse_uuid(task_id, "task_id")
    stmt = select(Project).where(Project.id == task_uuid, Project.user_id == user.id)
    project = db.execute(stmt).scalar_one_or_none()
    if project is None:
        raise NotFoundError("任务不存在")
    return {
        "task_id": project.id,
        "project_id": project.id,
        "status": project.status,
        "progress": int(project.progress),
    }


def _parse_uuid(raw: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(raw))
    except (TypeError, ValueError) as exc:
        raise ValidationAppError(f"{field_name} 不是合法 UUID") from exc
