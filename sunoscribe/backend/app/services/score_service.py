import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import ProjectStatus, ScoreType
from app.models.lyrics import Lyrics
from app.models.project import Project
from app.models.score import Score
from app.models.user import User
from app.utils.errors import NotFoundError, ValidationAppError


ALLOWED_EXPORT_FORMATS = {"midi", "pdf", "musicxml"}


def get_score_by_project_id(db: Session, *, user: User, project_id: str) -> Score:
    project_uuid = _parse_uuid(project_id, "project_id")
    stmt = (
        select(Score)
        .join(Project, Score.project_id == Project.id)
        .where(Project.id == project_uuid, Project.user_id == user.id)
    )
    score = db.execute(stmt).scalar_one_or_none()
    if score is None:
        raise NotFoundError("项目谱子不存在")
    return score


def generate_or_regenerate_score(
    db: Session,
    *,
    user: User,
    project_id: str,
    score_type: ScoreType,
    key: str,
) -> Score:
    project_uuid = _parse_uuid(project_id, "project_id")
    project_stmt = select(Project).where(Project.id == project_uuid, Project.user_id == user.id)
    project = db.execute(project_stmt).scalar_one_or_none()
    if project is None:
        raise NotFoundError("项目不存在")

    score_stmt = select(Score).where(Score.project_id == project.id)
    score = db.execute(score_stmt).scalar_one_or_none()
    if score is None:
        score = Score(project_id=project.id)
        db.add(score)

    now = datetime.now(timezone.utc).isoformat()
    score.score_type = score_type.value
    score.key = key
    score.score_data = {
        "generated_by": "backend_stub",
        "generated_at": now,
        "notes": [],
        "meta": {"project_id": str(project.id), "score_type": score.score_type, "key": score.key},
    }

    # Placeholder orchestration status transition for PRD flow.
    project.status = ProjectStatus.COMPLETED.value
    project.progress = 100
    db.add(project)
    db.add(score)

    lyrics_stmt = select(Lyrics).where(Lyrics.project_id == project.id)
    lyrics = db.execute(lyrics_stmt).scalar_one_or_none()
    if lyrics is None:
        db.add(Lyrics(project_id=project.id, text="", timeline=[]))

    db.commit()
    db.refresh(score)
    return score


def update_score(
    db: Session,
    *,
    user: User,
    score_id: str,
    score_type: ScoreType | None,
    key: str | None,
    vocal_range: str | None,
    recommended_voice: str | None,
    emotion: str | None,
    score_data: dict[str, Any] | None,
) -> Score:
    score_uuid = _parse_uuid(score_id, "score_id")
    stmt = (
        select(Score)
        .join(Project, Score.project_id == Project.id)
        .where(Score.id == score_uuid, Project.user_id == user.id)
    )
    score = db.execute(stmt).scalar_one_or_none()
    if score is None:
        raise NotFoundError("谱子不存在")

    if score_type is not None:
        score.score_type = score_type.value
    if key is not None:
        score.key = key
    if vocal_range is not None:
        score.vocal_range = vocal_range
    if recommended_voice is not None:
        score.recommended_voice = recommended_voice
    if emotion is not None:
        score.emotion = emotion
    if score_data is not None:
        score.score_data = score_data

    db.add(score)
    db.commit()
    db.refresh(score)
    return score


def export_score(
    db: Session,
    *,
    user: User,
    score_id: str,
    export_format: str,
) -> tuple[bytes, str, str]:
    fmt = str(export_format).strip().lower()
    if fmt not in ALLOWED_EXPORT_FORMATS:
        raise ValidationAppError("仅支持导出格式: midi/pdf/musicxml")

    score = get_score_by_id(db, user=user, score_id=score_id)

    if fmt == "midi":
        payload = score.score_data.get("midi_bytes")
        if isinstance(payload, str):
            content = payload.encode("utf-8")
        else:
            content = json.dumps(score.score_data, ensure_ascii=False).encode("utf-8")
        return content, "audio/midi", f"score_{score.id}.mid"

    if fmt == "pdf":
        content = json.dumps(score.score_data, ensure_ascii=False, indent=2).encode("utf-8")
        return content, "application/pdf", f"score_{score.id}.pdf"

    content = json.dumps(score.score_data, ensure_ascii=False, indent=2).encode("utf-8")
    return content, "application/vnd.recordare.musicxml+xml", f"score_{score.id}.musicxml"


def get_score_by_id(db: Session, *, user: User, score_id: str) -> Score:
    score_uuid = _parse_uuid(score_id, "score_id")
    stmt = (
        select(Score)
        .join(Project, Score.project_id == Project.id)
        .where(Score.id == score_uuid, Project.user_id == user.id)
    )
    score = db.execute(stmt).scalar_one_or_none()
    if score is None:
        raise NotFoundError("谱子不存在")
    return score


def _parse_uuid(raw: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(raw))
    except (TypeError, ValueError) as exc:
        raise ValidationAppError(f"{field_name} 不是合法 UUID") from exc
