from __future__ import annotations

import asyncio
import tempfile
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.enums import ProjectStatus, ScoreType
from app.models.lyrics import Lyrics
from app.models.project import Project
from app.models.score import Score
from app.models.user import User
from app.modules.score_ir.client_summary import build_score_revision_client_summary
from app.schemas.score_patch import ScorePatch
from app.services.audio_analysis_service import AudioAnalysisOptions, AudioAnalysisResult, AudioAnalysisService
from app.services.score_revision_service import (
    apply_score_patch,
    create_machine_score_revision,
    export_score_revision,
    get_score_revision_by_id,
    list_score_revisions,
)
from app.utils.errors import NotFoundError, ValidationAppError


def get_score_by_project_id(db: Session, *, user: User, project_id: str) -> Score:
    project_uuid = _parse_uuid(project_id, "project_id")
    stmt = (
        select(Score)
        .join(Project, Score.project_id == Project.id)
        .where(Project.id == project_uuid, Project.user_id == user.id)
    )
    score = db.execute(stmt).scalar_one_or_none()
    if score is None:
        raise NotFoundError("project score not found")
    return score


def get_score_by_id(db: Session, *, user: User, score_id: str) -> Score:
    score_uuid = _parse_uuid(score_id, "score_id")
    stmt = (
        select(Score)
        .join(Project, Score.project_id == Project.id)
        .where(Score.id == score_uuid, Project.user_id == user.id)
    )
    score = db.execute(stmt).scalar_one_or_none()
    if score is None:
        raise NotFoundError("score not found")
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
        raise NotFoundError("project not found")

    _require_project_audio(project)

    score_stmt = select(Score).where(Score.project_id == project.id)
    score = db.execute(score_stmt).scalar_one_or_none()
    if score is None:
        score = Score(project_id=project.id)
        if getattr(score, "id", None) is None:
            score.id = uuid.uuid4()
        db.add(score)

    analysis_result = _run_audio_analysis(project)
    revision = create_machine_score_revision(
        db,
        user=user,
        project=project,
        score=score,
        score_type=score_type,
        key=key,
        analysis_result=analysis_result,
    )

    lyrics_stmt = select(Lyrics).where(Lyrics.project_id == project.id)
    lyrics = db.execute(lyrics_stmt).scalar_one_or_none()
    if lyrics is None:
        lyrics = Lyrics(project_id=project.id, text="", timeline=[])

    lyrics.text = _build_lyrics_text(analysis_result.lyrics_segments)
    lyrics.timeline = list(analysis_result.lyrics_segments)

    project.status = ProjectStatus.COMPLETED.value
    project.progress = 100

    db.add(project)
    db.add(lyrics)
    db.add(score)
    db.add(revision)
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
    patch: ScorePatch | dict[str, Any] | None,
    revision_id: str | None = None,
) -> Score:
    score = get_score_by_id(db, user=user, score_id=score_id)
    if patch is None:
        raise ValidationAppError("score updates must provide a validated patch")

    revision = apply_score_patch(
        db,
        user=user,
        score_id=score_id,
        base_revision_id=revision_id,
        patch=patch,
        score_type=score_type or score.score_type,
        key=key or score.key,
        vocal_range=vocal_range,
        recommended_voice=recommended_voice,
        emotion=emotion,
    )

    db.add(score)
    db.add(revision)
    db.commit()
    db.refresh(score)
    return score


def export_score(
    db: Session,
    *,
    user: User,
    score_id: str,
    export_format: str,
    revision_id: str | None = None,
) -> tuple[bytes, str, str]:
    score = get_score_by_id(db, user=user, score_id=score_id)
    resolved_revision_id = revision_id or (str(score.current_revision_id) if score.current_revision_id else None)
    if not resolved_revision_id:
        raise ValidationAppError("score has no selected revision")
    return export_score_revision(
        db,
        user=user,
        revision_id=resolved_revision_id,
        export_format=export_format,
    )


def build_score_response(score: Score) -> dict[str, Any]:
    revisions = list_score_revisions_for_score(score)
    current_revision = score.current_revision
    return {
        "id": str(score.id),
        "project_id": str(score.project_id),
        "score_type": score.score_type,
        "key": score.key,
        "vocal_range": score.vocal_range,
        "recommended_voice": score.recommended_voice,
        "emotion": score.emotion,
        "score_data": score.score_data,
        "current_revision_id": str(score.current_revision_id) if score.current_revision_id else None,
        "current_revision": _serialize_revision(current_revision) if current_revision is not None else None,
        "revisions": revisions,
        "created_at": score.created_at.isoformat() if score.created_at else None,
        "updated_at": score.updated_at.isoformat() if score.updated_at else None,
    }


def list_score_revisions_for_score(score: Score) -> list[dict[str, Any]]:
    revisions = getattr(score, "revisions", None) or []
    return [_serialize_revision(revision) for revision in revisions]


def _serialize_revision(revision: Any) -> dict[str, Any]:
    artifact_ids: dict[str, str] = {}
    for artifact in list(getattr(revision, "artifacts", None) or []):
        artifact_type = str(getattr(artifact, "artifact_type", "") or "")
        artifact_id = getattr(artifact, "id", None)
        if artifact_type and artifact_id is not None:
            artifact_ids[artifact_type] = str(artifact_id)

    return {
        "id": str(revision.id),
        "project_id": str(revision.project_id),
        "score_id": str(revision.score_id),
        "parent_revision_id": str(revision.parent_revision_id) if revision.parent_revision_id else None,
        "revision_number": int(revision.revision_number),
        "revision_type": str(revision.revision_type),
        "score_type": str(revision.score_type),
        "key": str(revision.key),
        "artifact_ids": artifact_ids,
        "client_summary": build_score_revision_client_summary(revision=revision),
        "created_by_user_id": str(revision.created_by_user_id) if revision.created_by_user_id else None,
        "created_at": revision.created_at.isoformat() if revision.created_at else None,
        "updated_at": revision.updated_at.isoformat() if revision.updated_at else None,
    }


def _run_audio_analysis(project: Project) -> AudioAnalysisResult:
    _require_project_audio(project)
    raw_audio_path = str(project.audio_path or "").strip()

    with _materialize_analysis_input(raw_audio_path) as input_path:
        service = AudioAnalysisService()
        options = AudioAnalysisOptions(project_id=str(project.id))
        result = asyncio.run(service.process_audio(input_path, options))

    if not str(result.vocals_path or "").strip():
        raise ValidationAppError("required vocal separation stage did not produce vocals.wav")

    score_ir = result.score_ir if isinstance(result.score_ir, dict) else {}
    meta = score_ir.get("meta") if isinstance(score_ir.get("meta"), dict) else {}
    analysis_info = meta.get("analysis_info") if isinstance(meta.get("analysis_info"), dict) else {}
    if analysis_info.get("fallback"):
        raise ValidationAppError("audio analysis failed and produced fallback score_ir")

    notes = score_ir.get("notes")
    if not isinstance(notes, list) or not notes:
        raise ValidationAppError("audio analysis did not produce usable lead-vocal notes")

    return result


class _LocalAnalysisInput:
    def __init__(self, path: Path) -> None:
        self.path = path

    def __enter__(self) -> Path:
        if not self.path.exists() or not self.path.is_file():
            raise ValidationAppError("project source media file is missing or unreadable")
        return self.path

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class _TemporaryAnalysisInput:
    def __init__(self, source_uri: str) -> None:
        self.source_uri = source_uri
        self._temp_dir: tempfile.TemporaryDirectory[str] | None = None

    def __enter__(self) -> Path:
        bucket, object_name = _parse_s3_uri(self.source_uri)
        self._temp_dir = tempfile.TemporaryDirectory(prefix="sunoscribe-analysis-")
        target = Path(self._temp_dir.name) / Path(object_name).name
        if not target.suffix:
            target = target.with_suffix(".bin")
        _download_minio_object(bucket=bucket, object_name=object_name, target_path=target)
        return target

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._temp_dir is not None:
            self._temp_dir.cleanup()


def _materialize_analysis_input(raw_audio_path: str) -> _LocalAnalysisInput | _TemporaryAnalysisInput:
    if raw_audio_path.lower().startswith("s3://"):
        return _TemporaryAnalysisInput(raw_audio_path)
    return _LocalAnalysisInput(Path(raw_audio_path))


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme.lower() != "s3" or not parsed.netloc or not parsed.path.strip("/"):
        raise ValidationAppError("project object storage path is invalid")
    return parsed.netloc, unquote(parsed.path.lstrip("/"))


def _download_minio_object(*, bucket: str, object_name: str, target_path: Path) -> None:
    if not settings.minio_endpoint or not settings.minio_access_key or not settings.minio_secret_key:
        raise ValidationAppError("object storage is not fully configured")

    try:
        from minio import Minio
    except Exception as exc:
        raise ValidationAppError("missing minio dependency") from exc

    client_kwargs: dict[str, Any] = {
        "endpoint": settings.minio_endpoint,
        "access_key": settings.minio_access_key,
        "secret_key": settings.minio_secret_key,
        "secure": bool(settings.minio_secure),
    }
    if settings.minio_region:
        client_kwargs["region"] = settings.minio_region
    client = Minio(**client_kwargs)

    target_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        client.fget_object(bucket, object_name, str(target_path))
    except Exception as exc:
        raise ValidationAppError("project object storage media is missing or inaccessible") from exc


def _build_lyrics_text(lyrics_segments: list[dict[str, Any]]) -> str:
    lines = [
        str(segment.get("text", "")).strip()
        for segment in lyrics_segments
        if isinstance(segment, dict) and str(segment.get("text", "")).strip()
    ]
    return "\n".join(lines)


def _require_project_audio(project: Project) -> None:
    audio_path = str(project.audio_path or "").strip()
    if not audio_path:
        raise ValidationAppError("project is missing source audio/video")


def _parse_uuid(raw: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(raw))
    except (TypeError, ValueError) as exc:
        raise ValidationAppError(f"{field_name} must be a valid UUID") from exc
