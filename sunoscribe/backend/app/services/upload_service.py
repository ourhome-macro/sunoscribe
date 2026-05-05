import asyncio
import hashlib
import json
import mimetypes
import subprocess
import uuid
from pathlib import Path
from typing import Any

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.models.artifact import Artifact
from app.models.enums import ArtifactStatus, ArtifactStorageBackend, ArtifactType
from app.models.project import Project
from app.utils.errors import FileTooLargeError, UnsupportedFormatError, ValidationAppError

ALLOWED_AUDIO_EXTENSIONS = {"mp3", "wav", "flac", "aac", "ogg", "m4a"}
ALLOWED_VIDEO_EXTENSIONS = {"mp4", "mkv", "avi", "mov", "webm"}
MAX_UPLOAD_BYTES = 100 * 1024 * 1024


def probe_media_file(path: str | Path, media_kind: str, max_duration_sec: float) -> dict[str, Any]:
    target = Path(path)
    if not target.exists() or not target.is_file():
        raise ValidationAppError("上传文件不存在或不可访问")

    try:
        completed = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(target),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=30,
        )
    except FileNotFoundError as exc:
        raise ValidationAppError("服务器缺少 ffprobe，无法校验媒体文件") from exc
    except subprocess.TimeoutExpired as exc:
        raise ValidationAppError("媒体文件探测超时") from exc

    if completed.returncode != 0:
        raise UnsupportedFormatError("文件不是可解码的音视频媒体")

    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise UnsupportedFormatError("媒体文件探测结果无效") from exc

    streams = payload.get("streams") if isinstance(payload.get("streams"), list) else []
    has_audio = any(stream.get("codec_type") == "audio" for stream in streams if isinstance(stream, dict))
    has_video = any(stream.get("codec_type") == "video" for stream in streams if isinstance(stream, dict))
    if not has_audio:
        raise UnsupportedFormatError("文件不包含可分析的音频流")
    if media_kind == "video" and not has_video:
        raise UnsupportedFormatError("文件不包含视频流")

    duration = _extract_probe_duration(payload)
    if duration is None or duration <= 0:
        raise UnsupportedFormatError("无法读取媒体时长")
    if duration > float(max_duration_sec):
        raise FileTooLargeError(f"媒体时长超过 {int(max_duration_sec)} 秒限制")

    return {"duration_sec": duration, "has_audio": has_audio, "has_video": has_video}


def register_source_media_artifact(
    db: Session,
    *,
    project: Project,
    file_path: str,
    media_kind: str,
    original_filename: str | None,
    content_type: str | None,
    size: int | None = None,
    probe_metadata: dict[str, Any] | None = None,
) -> Artifact:
    path_obj = Path(str(file_path))
    payload = path_obj.read_bytes() if path_obj.exists() and path_obj.is_file() else b""
    mime_type = content_type or mimetypes.guess_type(str(original_filename or path_obj.name))[0]
    if not mime_type:
        mime_type = "video/mp4" if media_kind == "video" else "audio/mpeg"

    artifact = Artifact(
        project_id=project.id,
        artifact_type=ArtifactType.SOURCE_MEDIA.value,
        status=ArtifactStatus.AVAILABLE.value,
        storage_backend=(
            ArtifactStorageBackend.MINIO.value if str(file_path).lower().startswith("s3://") else ArtifactStorageBackend.WORKSPACE.value
        ),
        storage_path=str(file_path),
        filename=Path(original_filename or path_obj.name).name,
        mime_type=mime_type,
        file_size_bytes=int(size if size is not None else len(payload)) if (size is not None or payload) else None,
        checksum=hashlib.sha256(payload).hexdigest() if payload else None,
        artifact_metadata={
            "stage": "upload",
            "media_kind": str(media_kind),
            "original_filename": original_filename or path_obj.name,
            "content_type": content_type,
            "probe": dict(probe_metadata or {}),
        },
    )
    db.add(artifact)
    return artifact


def _extract_probe_duration(payload: dict[str, Any]) -> float | None:
    format_info = payload.get("format") if isinstance(payload.get("format"), dict) else {}
    duration_raw = format_info.get("duration")
    try:
        duration = float(duration_raw)
        if duration > 0:
            return duration
    except (TypeError, ValueError):
        pass

    stream_durations: list[float] = []
    streams = payload.get("streams") if isinstance(payload.get("streams"), list) else []
    for stream in streams:
        if not isinstance(stream, dict):
            continue
        try:
            duration = float(stream.get("duration"))
        except (TypeError, ValueError):
            continue
        if duration > 0:
            stream_durations.append(duration)
    return max(stream_durations) if stream_durations else None


def parse_uuid(value: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ValidationAppError(f"{field_name} 不是合法 UUID") from exc


def normalize_upload_backend(upload_backend: str) -> str:
    normalized = str(upload_backend or "").strip().lower()
    if normalized not in {"local", "minio"}:
        raise ValidationAppError("upload_backend 必须是 local 或 minio")
    return normalized


def validate_extension(filename: str, media_kind: str) -> str:
    suffix = Path(filename or "").suffix.lower().lstrip(".")
    if not suffix:
        raise UnsupportedFormatError("文件缺少扩展名")

    allowed = ALLOWED_AUDIO_EXTENSIONS if media_kind == "audio" else ALLOWED_VIDEO_EXTENSIONS
    if suffix not in allowed:
        raise UnsupportedFormatError(f"不支持的{media_kind}格式: .{suffix}")

    return suffix


def build_upload_storage_filename(extension: str) -> str:
    normalized_extension = str(extension or "").lower().lstrip(".")
    if not normalized_extension:
        raise UnsupportedFormatError("file extension is required")
    return f"{uuid.uuid4().hex}.{normalized_extension}"


def build_upload_target_path(
    *,
    uploads_root: Path,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    stored_filename: str | None = None,
    original_filename: str | None = None,
) -> Path:
    filename = stored_filename if stored_filename is not None else original_filename
    if not filename:
        raise ValidationAppError("stored_filename is required")
    safe_name = Path(filename).name
    return uploads_root / str(user_id) / str(project_id) / safe_name


def build_upload_object_key(
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    stored_filename: str | None = None,
    original_filename: str | None = None,
    base_path: str,
) -> str:
    filename = stored_filename if stored_filename is not None else original_filename
    if not filename:
        raise ValidationAppError("stored_filename is required")
    safe_name = Path(filename).name
    prefix = str(base_path or "").strip().strip("/")
    leaf = f"{user_id}/{project_id}/{safe_name}"
    return f"{prefix}/{leaf}" if prefix else leaf


async def save_upload_file(
    *,
    upload: UploadFile,
    media_kind: str,
    uploads_root: Path,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    upload_backend: str = "local",
    max_duration_sec: float = 600.0,
    minio_endpoint: str | None = None,
    minio_access_key: str | None = None,
    minio_secret_key: str | None = None,
    minio_bucket: str | None = None,
    minio_secure: bool = False,
    minio_region: str | None = None,
    minio_base_path: str = "uploads",
) -> tuple[str, int]:
    extension = validate_extension(upload.filename or "", media_kind)
    stored_filename = build_upload_storage_filename(extension)
    backend = normalize_upload_backend(upload_backend)

    if backend == "local":
        file_path, size = await _save_upload_file_local(
            upload=upload,
            uploads_root=uploads_root,
            user_id=user_id,
            project_id=project_id,
            stored_filename=stored_filename,
        )
        try:
            probe_media_file(file_path, media_kind, max_duration_sec)
        except Exception:
            try:
                Path(file_path).unlink(missing_ok=True)
            except OSError:
                pass
            raise
        return file_path, size

    return await _save_upload_file_minio(
        upload=upload,
        uploads_root=uploads_root,
        user_id=user_id,
        project_id=project_id,
        stored_filename=stored_filename,
        minio_endpoint=minio_endpoint,
        minio_access_key=minio_access_key,
        minio_secret_key=minio_secret_key,
        minio_bucket=minio_bucket,
        minio_secure=minio_secure,
        minio_region=minio_region,
        minio_base_path=minio_base_path,
        media_kind=media_kind,
        max_duration_sec=max_duration_sec,
    )


async def _save_upload_file_local(
    *,
    upload: UploadFile,
    uploads_root: Path,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    stored_filename: str,
) -> tuple[str, int]:
    target = build_upload_target_path(
        uploads_root=uploads_root,
        user_id=user_id,
        project_id=project_id,
        stored_filename=stored_filename,
    )
    target.parent.mkdir(parents=True, exist_ok=True)

    size = 0
    with target.open("wb") as out:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                out.close()
                try:
                    target.unlink(missing_ok=True)
                except OSError:
                    pass
                await upload.close()
                raise FileTooLargeError("文件大小超过 100MB 限制")
            out.write(chunk)

    await upload.close()
    return str(target), size


async def _save_upload_file_minio(
    *,
    upload: UploadFile,
    uploads_root: Path,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    stored_filename: str,
    minio_endpoint: str | None,
    minio_access_key: str | None,
    minio_secret_key: str | None,
    minio_bucket: str | None,
    minio_secure: bool,
    minio_region: str | None,
    minio_base_path: str,
    media_kind: str,
    max_duration_sec: float,
) -> tuple[str, int]:
    _validate_minio_config(
        endpoint=minio_endpoint,
        access_key=minio_access_key,
        secret_key=minio_secret_key,
        bucket=minio_bucket,
    )
    object_key = build_upload_object_key(
        user_id=user_id,
        project_id=project_id,
        stored_filename=stored_filename,
        base_path=minio_base_path,
    )

    temp_dir = uploads_root / ".upload_tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / stored_filename

    size = 0
    try:
        size = await _read_upload_to_temp_file(upload=upload, temp_path=temp_path)
        probe_media_file(temp_path, media_kind, max_duration_sec)
        await asyncio.to_thread(
            _put_file_to_minio,
            temp_path,
            size,
            upload.content_type or "application/octet-stream",
            minio_endpoint or "",
            minio_access_key or "",
            minio_secret_key or "",
            minio_bucket or "",
            minio_secure,
            minio_region,
            object_key,
        )
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass

    return f"s3://{minio_bucket}/{object_key}", size


async def _read_upload_to_temp_file(*, upload: UploadFile, temp_path: Path) -> int:
    size = 0
    with temp_path.open("wb") as out:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                out.close()
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
                await upload.close()
                raise FileTooLargeError("文件大小超过 100MB 限制")
            out.write(chunk)
    await upload.close()
    return size


def _put_file_to_minio(
    temp_path: Path,
    size: int,
    content_type: str,
    minio_endpoint: str,
    minio_access_key: str,
    minio_secret_key: str,
    minio_bucket: str,
    minio_secure: bool,
    minio_region: str | None,
    object_key: str,
) -> None:
    try:
        from minio import Minio
    except Exception as exc:
        raise ValidationAppError("未安装 minio 依赖，请先安装 minio 包") from exc

    client_kwargs: dict[str, Any] = {
        "endpoint": minio_endpoint,
        "access_key": minio_access_key,
        "secret_key": minio_secret_key,
        "secure": bool(minio_secure),
    }
    if minio_region:
        client_kwargs["region"] = minio_region
    client = Minio(**client_kwargs)

    if not client.bucket_exists(minio_bucket):
        client.make_bucket(minio_bucket)

    with temp_path.open("rb") as data:
        client.put_object(
            bucket_name=minio_bucket,
            object_name=object_key,
            data=data,
            length=size,
            content_type=content_type,
        )


def _validate_minio_config(*, endpoint: str | None, access_key: str | None, secret_key: str | None, bucket: str | None) -> None:
    if not endpoint:
        raise ValidationAppError("缺少 MinIO 配置: minio_endpoint")
    if not access_key:
        raise ValidationAppError("缺少 MinIO 配置: minio_access_key")
    if not secret_key:
        raise ValidationAppError("缺少 MinIO 配置: minio_secret_key")
    if not bucket:
        raise ValidationAppError("缺少 MinIO 配置: minio_bucket")
