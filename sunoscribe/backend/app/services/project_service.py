import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import ProjectStatus, SourceType
from app.models.project import Project
from app.models.user import User
from app.utils.errors import NotFoundError, ValidationAppError


def create_project(
    db: Session,
    *,
    user: User,
    name: str,
    source_type: SourceType,
    source_url: str | None,
    audio_path: str | None,
) -> Project:
    project = Project(
        user_id=user.id,
        name=name,
        source_type=source_type.value,
        source_url=source_url,
        audio_path=audio_path,
        status=ProjectStatus.PENDING.value,
        progress=0,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def list_projects(
    db: Session,
    *,
    user: User,
    page: int,
    page_size: int,
) -> tuple[list[Project], int]:
    count_stmt = select(func.count(Project.id)).where(Project.user_id == user.id)
    total = int(db.execute(count_stmt).scalar_one() or 0)

    data_stmt = (
        select(Project)
        .where(Project.user_id == user.id)
        .order_by(Project.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    projects = list(db.execute(data_stmt).scalars().all())
    return projects, total


def get_project_by_id(db: Session, *, user: User, project_id: str) -> Project:
    project_uuid = _parse_uuid(project_id, "project_id")
    stmt = select(Project).where(Project.id == project_uuid, Project.user_id == user.id)
    project = db.execute(stmt).scalar_one_or_none()
    if project is None:
        raise NotFoundError("项目不存在")
    return project


def update_project(
    db: Session,
    *,
    project: Project,
    name: str | None,
    source_url: str | None,
    audio_path: str | None,
    status: ProjectStatus | None,
    progress: int | None,
) -> Project:
    if name is not None:
        project.name = name
    if source_url is not None:
        project.source_url = source_url
    if audio_path is not None:
        project.audio_path = audio_path
    if status is not None:
        project.status = status.value
    if progress is not None:
        project.progress = max(0, min(100, int(progress)))

    if project.status == ProjectStatus.COMPLETED.value and project.progress < 100:
        project.progress = 100

    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def update_project_audio_path(db: Session, *, project: Project, audio_path: str) -> Project:
    project.audio_path = audio_path
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def delete_project(db: Session, *, project: Project) -> None:
    db.delete(project)
    db.commit()


def _parse_uuid(raw: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(raw))
    except (TypeError, ValueError) as exc:
        raise ValidationAppError(f"{field_name} 不是合法 UUID") from exc
