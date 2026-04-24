from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.schemas.upload import UploadResponse
from app.services.project_service import get_project_by_id
from app.services.upload_service import parse_uuid, save_upload_file
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
    project = get_project_by_id(db, user=current_user, project_id=project_id)
    project_uuid = parse_uuid(project_id, "project_id")
    file_path, size = await save_upload_file(
        upload=file,
        media_kind="audio",
        uploads_root=Path(settings.uploads_root),
        user_id=current_user.id,
        project_id=project_uuid,
        upload_backend=settings.upload_backend,
        minio_endpoint=settings.minio_endpoint,
        minio_access_key=settings.minio_access_key,
        minio_secret_key=settings.minio_secret_key,
        minio_bucket=settings.minio_bucket,
        minio_secure=settings.minio_secure,
        minio_region=settings.minio_region,
        minio_base_path=settings.minio_base_path,
    )
    project.audio_path = file_path
    db.add(project)
    db.commit()
    db.refresh(project)
    data = UploadResponse(file_path=file_path, project_id=project_uuid, filename=file.filename or "", size=size)
    return success_response(data.model_dump(), "音频上传成功")


@router.post("/video")
async def upload_video_api(
    project_id: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    project = get_project_by_id(db, user=current_user, project_id=project_id)
    project_uuid = parse_uuid(project_id, "project_id")
    file_path, size = await save_upload_file(
        upload=file,
        media_kind="video",
        uploads_root=Path(settings.uploads_root),
        user_id=current_user.id,
        project_id=project_uuid,
        upload_backend=settings.upload_backend,
        minio_endpoint=settings.minio_endpoint,
        minio_access_key=settings.minio_access_key,
        minio_secret_key=settings.minio_secret_key,
        minio_bucket=settings.minio_bucket,
        minio_secure=settings.minio_secure,
        minio_region=settings.minio_region,
        minio_base_path=settings.minio_base_path,
    )
    project.audio_path = file_path
    db.add(project)
    db.commit()
    db.refresh(project)
    data = UploadResponse(file_path=file_path, project_id=project_uuid, filename=file.filename or "", size=size)
    return success_response(data.model_dump(), "视频上传成功")
