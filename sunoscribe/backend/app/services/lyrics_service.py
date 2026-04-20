import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.lyrics import Lyrics
from app.models.project import Project
from app.models.user import User
from app.utils.errors import NotFoundError, ValidationAppError


def get_lyrics_by_project_id(db: Session, *, user: User, project_id: str) -> Lyrics:
    project_uuid = _parse_uuid(project_id, "project_id")
    stmt = (
        select(Lyrics)
        .join(Project, Lyrics.project_id == Project.id)
        .where(Project.id == project_uuid, Project.user_id == user.id)
    )
    lyrics = db.execute(stmt).scalar_one_or_none()
    if lyrics is None:
        raise NotFoundError("项目歌词不存在")
    return lyrics


def update_lyrics(
    db: Session,
    *,
    user: User,
    lyrics_id: str,
    text: str | None,
    timeline: list[Any] | dict[str, Any] | None,
) -> Lyrics:
    lyrics_uuid = _parse_uuid(lyrics_id, "lyrics_id")
    stmt = (
        select(Lyrics)
        .join(Project, Lyrics.project_id == Project.id)
        .where(Lyrics.id == lyrics_uuid, Project.user_id == user.id)
    )
    lyrics = db.execute(stmt).scalar_one_or_none()
    if lyrics is None:
        raise NotFoundError("歌词不存在")

    if text is not None:
        lyrics.text = text
    if timeline is not None:
        lyrics.timeline = timeline

    db.add(lyrics)
    db.commit()
    db.refresh(lyrics)
    return lyrics


def _parse_uuid(raw: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(raw))
    except (TypeError, ValueError) as exc:
        raise ValidationAppError(f"{field_name} 不是合法 UUID") from exc
