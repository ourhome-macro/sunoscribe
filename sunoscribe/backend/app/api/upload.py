from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.schemas.upload import UploadResponse
from app.services.project_service import get_project_by_id, update_project_audio_path
from app.services.upload_service import parse_uuid, probe_media_file, register_source_media_artifact, save_upload_file
from app.utils.dependencies import get_current_user
from app.utils.responses import success_response

router = APIRouter(prefix="/upload", tags=["upload"])


@router.post("/audio")
async def upload_audio_api(
    project_id: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    project_uuid = parse_uuid(project_id, "project_id")
    project = get_project_by_id(db, user=current_user, project_id=str(project_uuid))
    file_path, size = await save_upload_file(
        upload=file,
        media_kind="audio",
        uploads_root=Path(settings.uploads_root),
        user_id=current_user.id,
        project_id=project_uuid,
        upload_backend=settings.upload_backend,
        max_duration_sec=settings.max_media_duration_sec,
        minio_endpoint=settings.minio_endpoint,
        minio_access_key=settings.minio_access_key,
        minio_secret_key=settings.minio_secret_key,
        minio_bucket=settings.minio_bucket,
        minio_secure=settings.minio_secure,
        minio_region=settings.minio_region,
        minio_base_path=settings.minio_base_path,
    )
    update_project_audio_path(
        db,
        project=project,
        audio_path=file_path,
    )
    artifact = register_source_media_artifact(
        db,
        project=project,
        file_path=file_path,
        media_kind="audio",
        original_filename=file.filename or "",
        content_type=getattr(file, "content_type", None),
        size=size,
        probe_metadata=_safe_probe_uploaded_media(file_path, "audio"),
    )
    db.commit()
    data = UploadResponse(
        file_path=file_path,
        project_id=project_uuid,
        filename=file.filename or "",
        size=size,
        artifact_id=artifact.id,
    )
    return success_response(data.model_dump(), "音频上传成功")


@router.post("/video")
async def upload_video_api(
    project_id: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    project_uuid = parse_uuid(project_id, "project_id")
    project = get_project_by_id(db, user=current_user, project_id=str(project_uuid))
    file_path, size = await save_upload_file(
        upload=file,
        media_kind="video",
        uploads_root=Path(settings.uploads_root),
        user_id=current_user.id,
        project_id=project_uuid,
        upload_backend=settings.upload_backend,
        max_duration_sec=settings.max_media_duration_sec,
        minio_endpoint=settings.minio_endpoint,
        minio_access_key=settings.minio_access_key,
        minio_secret_key=settings.minio_secret_key,
        minio_bucket=settings.minio_bucket,
        minio_secure=settings.minio_secure,
        minio_region=settings.minio_region,
        minio_base_path=settings.minio_base_path,
    )
    update_project_audio_path(
        db,
        project=project,
        audio_path=file_path,
    )
    artifact = register_source_media_artifact(
        db,
        project=project,
        file_path=file_path,
        media_kind="video",
        original_filename=file.filename or "",
        content_type=getattr(file, "content_type", None),
        size=size,
        probe_metadata=_safe_probe_uploaded_media(file_path, "video"),
    )
    db.commit()
    data = UploadResponse(
        file_path=file_path,
        project_id=project_uuid,
        filename=file.filename or "",
        size=size,
        artifact_id=artifact.id,
    )
    return success_response(data.model_dump(), "视频上传成功")


def _safe_probe_uploaded_media(file_path: str, media_kind: str) -> dict:
    if str(file_path).lower().startswith("s3://"):
        return {}
    try:
        return probe_media_file(file_path, media_kind, settings.max_media_duration_sec)
    except Exception:
        return {}
