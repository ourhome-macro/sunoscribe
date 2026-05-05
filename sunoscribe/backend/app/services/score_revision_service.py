from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.artifact import Artifact
from app.models.enums import ArtifactStatus, ArtifactStorageBackend, ArtifactType, ScoreRevisionType, ScoreType
from app.models.project import Project
from app.models.score import Score
from app.models.score_revision import ScoreRevision
from app.models.user import User
from app.schemas.score_patch import ScorePatch
from app.services.patch_validator import PatchValidator
from app.services.render_export_service import RenderExportService
from app.services.workspace import ProjectWorkspace
from app.utils.errors import NotFoundError, ValidationAppError

patch_validator = PatchValidator()
render_export_service = RenderExportService()


def create_machine_score_revision(
    db: Session,
    *,
    user: User | None = None,
    project: Project | None = None,
    project_id: str | None = None,
    score: Score | None = None,
    score_type: ScoreType | str = ScoreType.JIANPU,
    key: str = "C Major",
    analysis_result: Any | None = None,
    score_ir: dict[str, Any] | None = None,
    score_data: dict[str, Any] | None = None,
    task_id: str | None = None,
) -> ScoreRevision:
    project_obj = _resolve_project(db, user=user, project=project, project_id=project_id)
    _require_project_audio(project_obj)

    revision_score_ir = _resolve_score_ir(analysis_result=analysis_result, score_ir=score_ir, score_data=score_data)
    revision_score_data = _resolve_score_data(analysis_result=analysis_result, score_data=score_data, score_ir=revision_score_ir)
    _validate_machine_transcription(score_ir=revision_score_ir, score_data=revision_score_data, analysis_result=analysis_result)

    score_obj = score or _get_or_create_score(db, project=project_obj)
    _ensure_entity_uuid(score_obj)

    normalized_score_type = _normalize_score_type(score_type)
    revision_number = _next_revision_number(db, score_id=score_obj.id)
    parent_revision_id = getattr(score_obj, "current_revision_id", None)

    revision = ScoreRevision(
        project_id=project_obj.id,
        score_id=score_obj.id,
        parent_revision_id=parent_revision_id,
        created_by_user_id=None,
        revision_number=revision_number,
        revision_type=ScoreRevisionType.MACHINE.value,
        score_type=normalized_score_type,
        key=str(key),
        vocal_range=getattr(score_obj, "vocal_range", None),
        recommended_voice=getattr(score_obj, "recommended_voice", None),
        emotion=getattr(score_obj, "emotion", None),
        score_ir=revision_score_ir,
        score_data=revision_score_data,
        patch_data={},
        revision_metadata=_build_machine_revision_metadata(project_obj=project_obj, analysis_result=analysis_result),
    )
    _ensure_entity_uuid(revision)
    revision.score = score_obj

    _sync_score_from_revision(score_obj, revision)
    score_obj.current_revision = revision
    db.add(score_obj)
    db.add(revision)

    _register_analysis_artifacts(
        db,
        project=project_obj,
        score=score_obj,
        revision=revision,
        analysis_result=analysis_result,
        task_id=task_id,
    )
    render_export_service.ensure_core_exports(db, score=score_obj, revision=revision, task_id=task_id)
    return revision


def apply_score_patch(
    db: Session,
    *,
    user: User,
    patch: ScorePatch | dict[str, Any],
    score_id: str | None = None,
    revision_id: str | None = None,
    score_revision_id: str | None = None,
    base_revision_id: str | None = None,
    score_type: ScoreType | str | None = None,
    key: str | None = None,
    vocal_range: str | None = None,
    recommended_voice: str | None = None,
    emotion: str | None = None,
) -> ScoreRevision:
    patch_obj = patch if isinstance(patch, ScorePatch) else ScorePatch.model_validate(patch)
    base_revision = _resolve_base_revision(
        db,
        user=user,
        score_id=score_id,
        revision_id=revision_id or score_revision_id or base_revision_id,
    )
    score = base_revision.score
    if score is None:
        raise ValidationAppError("base score revision is detached from its score")

    validation_result = patch_validator.validate_and_apply(
        score_ir=base_revision.score_ir,
        score_data=base_revision.score_data,
        patch=patch_obj,
    )

    revision = ScoreRevision(
        project_id=base_revision.project_id,
        score_id=base_revision.score_id,
        parent_revision_id=base_revision.id,
        created_by_user_id=user.id,
        revision_number=_next_revision_number(db, score_id=base_revision.score_id),
        revision_type=ScoreRevisionType.USER.value,
        score_type=_normalize_score_type(score_type or base_revision.score_type),
        key=str(key or base_revision.key),
        vocal_range=vocal_range if vocal_range is not None else base_revision.vocal_range,
        recommended_voice=(
            recommended_voice if recommended_voice is not None else base_revision.recommended_voice
        ),
        emotion=emotion if emotion is not None else base_revision.emotion,
        score_ir=validation_result.score_ir,
        score_data=validation_result.score_data,
        patch_data=patch_obj.model_dump(),
        revision_metadata={
            **(base_revision.revision_metadata if isinstance(base_revision.revision_metadata, dict) else {}),
            "base_revision_id": str(base_revision.id),
            "patch_summary": patch_obj.summary,
        },
    )
    _ensure_entity_uuid(revision)
    revision.score = score
    _sync_score_from_revision(score, revision)
    score.current_revision = revision
    db.add(score)
    db.add(revision)
    render_export_service.ensure_core_exports(db, score=score, revision=revision)
    return revision


def export_score_revision(
    db: Session,
    *,
    user: User,
    export_format: str,
    revision_id: str | None = None,
    score_revision_id: str | None = None,
) -> tuple[bytes, str, str]:
    revision = get_score_revision_by_id(db, user=user, revision_id=revision_id or score_revision_id)
    score = revision.score
    if score is None:
        raise ValidationAppError("score revision is detached from its score")

    payload, media_type, filename = render_export_service.load_export_bytes(
        db,
        score=score,
        revision=revision,
        export_format=export_format,
    )
    db.commit()
    return payload, media_type, filename


def get_score_revision_by_id(db: Session, *, user: User, revision_id: str | None) -> ScoreRevision:
    if not revision_id:
        raise ValidationAppError("revision_id is required")
    revision_uuid = _parse_uuid(revision_id, "revision_id")
    stmt = (
        select(ScoreRevision)
        .join(Score, ScoreRevision.score_id == Score.id)
        .join(Project, Score.project_id == Project.id)
        .where(ScoreRevision.id == revision_uuid, Project.user_id == user.id)
    )
    revision = db.execute(stmt).scalar_one_or_none()
    if revision is None:
        raise NotFoundError("score revision not found")
    return revision


def list_score_revisions(db: Session, *, score_id: uuid.UUID) -> list[ScoreRevision]:
    stmt = select(ScoreRevision).where(ScoreRevision.score_id == score_id).order_by(ScoreRevision.revision_number.asc())
    return list(db.execute(stmt).scalars().all())


def _resolve_project(
    db: Session,
    *,
    user: User | None,
    project: Project | None,
    project_id: str | None,
) -> Project:
    if project is not None:
        return project
    if not project_id or user is None:
        raise ValidationAppError("project context is required")
    project_uuid = _parse_uuid(project_id, "project_id")
    stmt = select(Project).where(Project.id == project_uuid, Project.user_id == user.id)
    project_obj = db.execute(stmt).scalar_one_or_none()
    if project_obj is None:
        raise NotFoundError("project not found")
    return project_obj


def _get_or_create_score(db: Session, *, project: Project) -> Score:
    stmt = select(Score).where(Score.project_id == project.id)
    score = db.execute(stmt).scalar_one_or_none()
    if score is not None:
        return score

    score = Score(project_id=project.id)
    _ensure_entity_uuid(score)
    db.add(score)
    return score


def _resolve_base_revision(
    db: Session,
    *,
    user: User,
    score_id: str | None,
    revision_id: str | None,
) -> ScoreRevision:
    if revision_id:
        return get_score_revision_by_id(db, user=user, revision_id=revision_id)

    if not score_id:
        raise ValidationAppError("score_id or revision_id is required")

    score_uuid = _parse_uuid(score_id, "score_id")
    stmt = (
        select(Score)
        .join(Project, Score.project_id == Project.id)
        .where(Score.id == score_uuid, Project.user_id == user.id)
    )
    score = db.execute(stmt).scalar_one_or_none()
    if score is None:
        raise NotFoundError("score not found")
    if score.current_revision is None:
        raise ValidationAppError("score has no current revision")
    return score.current_revision


def _resolve_score_ir(
    *,
    analysis_result: Any | None,
    score_ir: dict[str, Any] | None,
    score_data: dict[str, Any] | None,
) -> dict[str, Any]:
    if isinstance(score_ir, dict):
        return score_ir
    nested = getattr(analysis_result, "score_ir", None)
    if isinstance(nested, dict):
        return nested
    if isinstance(score_data, dict):
        nested = score_data.get("score_ir")
        if isinstance(nested, dict):
            return nested
    raise ValidationAppError("machine revision requires canonical score_ir")


def _resolve_score_data(
    *,
    analysis_result: Any | None,
    score_data: dict[str, Any] | None,
    score_ir: dict[str, Any],
) -> dict[str, Any]:
    if isinstance(score_data, dict):
        resolved = dict(score_data)
    else:
        nested = getattr(analysis_result, "score_data", None)
        resolved = dict(nested) if isinstance(nested, dict) else {}

    if "score_ir" not in resolved:
        resolved["score_ir"] = score_ir
    return resolved


def _validate_machine_transcription(
    *,
    score_ir: dict[str, Any],
    score_data: dict[str, Any],
    analysis_result: Any | None,
) -> None:
    meta = score_ir.get("meta") if isinstance(score_ir.get("meta"), dict) else {}
    analysis_info = meta.get("analysis_info") if isinstance(meta.get("analysis_info"), dict) else {}
    if analysis_info.get("fallback"):
        raise ValidationAppError("audio analysis produced fallback score_ir")

    notes = score_ir.get("notes")
    if not isinstance(notes, list) or not notes:
        raise ValidationAppError("audio analysis produced no notes")

    score_data_meta = score_data.get("meta") if isinstance(score_data.get("meta"), dict) else {}
    score_data_analysis = (
        score_data_meta.get("analysis_info") if isinstance(score_data_meta.get("analysis_info"), dict) else {}
    )
    if score_data_analysis.get("fallback"):
        raise ValidationAppError("audio analysis produced fallback score_data")

    if analysis_result is not None:
        vocals_path = str(getattr(analysis_result, "vocals_path", "") or "").strip()
        if not vocals_path:
            raise ValidationAppError("required vocals stem artifact is missing")


def _build_machine_revision_metadata(*, project_obj: Project, analysis_result: Any | None) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "project_id": str(project_obj.id),
        "source_audio_path": str(project_obj.audio_path or ""),
    }
    if analysis_result is None:
        return metadata

    for field_name in (
        "source_audio_path",
        "normalized_audio_path",
        "vocals_path",
        "accompaniment_path",
        "stem_paths",
        "warnings",
        "alignment_source",
        "alignment_accepted",
    ):
        value = getattr(analysis_result, field_name, None)
        if value is not None:
            metadata[field_name] = value
    return metadata


def _register_analysis_artifacts(
    db: Session,
    *,
    project: Project,
    score: Score,
    revision: ScoreRevision,
    analysis_result: Any | None,
    task_id: str | None,
) -> None:
    if analysis_result is None:
        return

    workspace = ProjectWorkspace(project_id=str(project.id))
    source_media_mime = _guess_source_media_mime(getattr(analysis_result, "source_audio_path", None))
    candidates = [
        (ArtifactType.SOURCE_MEDIA.value, getattr(analysis_result, "source_audio_path", None), source_media_mime),
        (ArtifactType.CANONICAL_AUDIO.value, getattr(analysis_result, "normalized_audio_path", None), "audio/wav"),
        (ArtifactType.VOCALS_STEM.value, getattr(analysis_result, "vocals_path", None), "audio/wav"),
        (
            ArtifactType.ACCOMPANIMENT_STEM.value,
            getattr(analysis_result, "accompaniment_path", None),
            "audio/wav",
        ),
        (ArtifactType.LYRICS_SEGMENTS.value, workspace.lyrics_segments_path, "application/json"),
        (ArtifactType.PITCH_ANALYSIS.value, workspace.pitch_result_path, "application/json"),
        (ArtifactType.F0_TRACK.value, workspace.f0_track_path, "application/json"),
        (ArtifactType.NOTE_CANDIDATES.value, workspace.note_candidates_path, "application/json"),
        (ArtifactType.RHYTHM_GRID.value, workspace.rhythm_grid_path, "application/json"),
        (ArtifactType.ANALYSIS_IR.value, workspace.analysis_ir_path, "application/json"),
        (ArtifactType.SCORE_IR.value, workspace.score_ir_path, "application/json"),
        (ArtifactType.ALIGNMENT.value, workspace.baseline_alignment_path, "application/json"),
        (ArtifactType.ALIGNMENT.value, workspace.final_alignment_path, "application/json"),
    ]
    for artifact_type, raw_path, mime_type in candidates:
        _record_file_artifact(
            db,
            project_id=project.id,
            score_id=score.id,
            revision_id=revision.id,
            artifact_type=artifact_type,
            raw_path=raw_path,
            mime_type=mime_type,
            task_id=task_id,
        )


def _record_file_artifact(
    db: Session,
    *,
    project_id: uuid.UUID,
    score_id: uuid.UUID,
    revision_id: uuid.UUID,
    artifact_type: str,
    raw_path: Any,
    mime_type: str,
    task_id: str | None,
) -> None:
    path_text = str(raw_path or "").strip()
    if not path_text:
        return
    path_obj = Path(path_text)
    if not path_obj.exists() or not path_obj.is_file():
        return

    payload = path_obj.read_bytes()
    artifact = Artifact(
        project_id=project_id,
        score_id=score_id,
        score_revision_id=revision_id,
        task_id=_optional_uuid(task_id),
        artifact_type=artifact_type,
        status=ArtifactStatus.AVAILABLE.value,
        storage_backend=ArtifactStorageBackend.WORKSPACE.value,
        storage_path=str(path_obj),
        filename=path_obj.name,
        mime_type=mime_type,
        file_size_bytes=len(payload),
        checksum=hashlib.sha256(payload).hexdigest(),
        artifact_metadata={},
    )
    db.add(artifact)


def _guess_source_media_mime(raw_path: Any) -> str:
    import mimetypes

    guessed, _ = mimetypes.guess_type(str(raw_path or ""))
    return guessed or "application/octet-stream"


def _sync_score_from_revision(score: Score, revision: ScoreRevision) -> None:
    score.current_revision_id = revision.id
    score.score_type = revision.score_type
    score.key = revision.key
    score.vocal_range = revision.vocal_range
    score.recommended_voice = revision.recommended_voice
    score.emotion = revision.emotion
    score.score_data = dict(revision.score_data or {})


def _next_revision_number(db: Session, *, score_id: uuid.UUID) -> int:
    stmt = select(func.max(ScoreRevision.revision_number)).where(ScoreRevision.score_id == score_id)
    value = db.execute(stmt).scalar_one_or_none()
    return int(value or 0) + 1


def _normalize_score_type(score_type: ScoreType | str) -> str:
    if isinstance(score_type, ScoreType):
        return score_type.value
    try:
        return ScoreType(str(score_type)).value
    except ValueError as exc:
        raise ValidationAppError(f"invalid score_type: {score_type}") from exc


def _require_project_audio(project: Project) -> None:
    audio_path = str(getattr(project, "audio_path", "") or "").strip()
    if not audio_path:
        raise ValidationAppError("project is missing source audio/video")


def _ensure_entity_uuid(entity: Any) -> None:
    if getattr(entity, "id", None) is None:
        entity.id = uuid.uuid4()


def _parse_uuid(raw: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(raw))
    except (TypeError, ValueError) as exc:
        raise ValidationAppError(f"{field_name} must be a valid UUID") from exc


def _optional_uuid(raw: str | uuid.UUID | None) -> uuid.UUID | None:
    if raw is None or isinstance(raw, uuid.UUID):
        return raw
    text = str(raw).strip()
    if not text:
        return None
    return uuid.UUID(text)
