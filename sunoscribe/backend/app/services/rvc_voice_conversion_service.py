from __future__ import annotations

import hashlib
import json
import mimetypes
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib import error, request

from sqlalchemy.orm import Session

from app.config import settings
from app.models.artifact import Artifact
from app.models.enums import ArtifactStatus, ArtifactStorageBackend, ArtifactType
from app.models.score_revision import ScoreRevision
from app.modules.agents import RvcJobSpec, RvcVoiceConversionResult
from app.services.workspace import ProjectWorkspace
from app.utils.errors import ValidationAppError


@dataclass(slots=True)
class ExternalRvcClient:
    """Small synchronous client for an external RVC voice-conversion service."""

    endpoint_url: str | None = None
    api_key: str | None = None
    timeout_seconds: int = 600

    def convert_voice(
        self,
        *,
        vocal_path: Path,
        voice_model_id: str,
        transpose_semitones: int = 0,
        request_metadata: dict[str, Any] | None = None,
    ) -> tuple[bytes, str, dict[str, Any]]:
        endpoint = str(self.endpoint_url or settings.rvc_endpoint_url or "").strip()
        if not endpoint:
            raise ValidationAppError("rvc_endpoint_url is not configured")
        if not vocal_path.exists() or not vocal_path.is_file():
            raise ValidationAppError("vocal stem file is unavailable for RVC conversion")

        boundary = f"----sunoscribe-rvc-{uuid.uuid4().hex}"
        payload = self._multipart_body(
            boundary=boundary,
            fields={
                "voice_model_id": str(voice_model_id),
                "transpose_semitones": str(int(transpose_semitones)),
                "mode": "voice_conversion",
                "metadata": json.dumps(request_metadata or {}, ensure_ascii=False),
            },
            file_field="vocals",
            file_path=vocal_path,
        )
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        api_key = str(self.api_key or settings.rvc_api_key or "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        req = request.Request(endpoint, data=payload, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=max(1, int(self.timeout_seconds))) as response:
                content_type = str(response.headers.get("Content-Type") or "application/octet-stream")
                return response.read(), content_type, {"status_code": int(response.status)}
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise ValidationAppError(
                "external RVC voice conversion failed",
                details={"status_code": exc.code, "response": detail},
            ) from exc
        except error.URLError as exc:
            raise ValidationAppError("external RVC voice conversion is unreachable", details={"reason": str(exc)}) from exc

    def _multipart_body(
        self,
        *,
        boundary: str,
        fields: dict[str, str],
        file_field: str,
        file_path: Path,
    ) -> bytes:
        chunks: list[bytes] = []
        for name, value in fields.items():
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode(),
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                    str(value).encode("utf-8"),
                    b"\r\n",
                ]
            )
        content_type = mimetypes.guess_type(str(file_path))[0] or "audio/wav"
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                (
                    f'Content-Disposition: form-data; name="{file_field}"; '
                    f'filename="{file_path.name}"\r\n'
                ).encode(),
                f"Content-Type: {content_type}\r\n\r\n".encode(),
                file_path.read_bytes(),
                b"\r\n",
                f"--{boundary}--\r\n".encode(),
            ]
        )
        return b"".join(chunks)


@dataclass(slots=True)
class RvcVoiceConversionService:
    client: ExternalRvcClient = field(default_factory=ExternalRvcClient)

    def convert(
        self,
        db: Session,
        *,
        revision: ScoreRevision,
        spec: RvcJobSpec,
        task_id: str | None = None,
    ) -> tuple[RvcVoiceConversionResult, Artifact]:
        if spec.mode != "voice_conversion":
            raise ValidationAppError("RVC voice conversion requires mode=voice_conversion")
        vocal_artifact = self._require_artifact(
            revision=revision,
            artifact_id=spec.vocal_stem_artifact_id,
            artifact_type=ArtifactType.VOCALS_STEM.value,
        )
        vocal_path = Path(str(vocal_artifact.storage_path or ""))
        response_bytes, content_type, response_metadata = self.client.convert_voice(
            vocal_path=vocal_path,
            voice_model_id=spec.voice_model_id,
            transpose_semitones=spec.transpose_semitones,
            request_metadata={
                "project_id": str(revision.project_id),
                "revision_id": str(revision.id),
                "source_vocal_artifact_id": str(vocal_artifact.id),
            },
        )
        artifact = self._record_rvc_vocal_artifact(
            db,
            revision=revision,
            source_artifact=vocal_artifact,
            payload=response_bytes,
            content_type=content_type,
            spec=spec,
            response_metadata=response_metadata,
            task_id=task_id,
        )
        result = RvcVoiceConversionResult(
            project_id=str(revision.project_id),
            revision_id=str(revision.id),
            rvc_vocal_artifact_id=str(artifact.id),
            source_vocal_stem_artifact_id=str(vocal_artifact.id),
            voice_model_id=spec.voice_model_id,
            transpose_semitones=spec.transpose_semitones,
            rvc_backend=str(spec.rvc_backend or "external"),
            warnings=list(spec.warnings or []),
        )
        return result, artifact

    def _require_artifact(self, *, revision: ScoreRevision, artifact_id: str | None, artifact_type: str) -> Artifact:
        if not artifact_id:
            raise ValidationAppError(f"{artifact_type} artifact id is required")
        for artifact in list(getattr(revision, "artifacts", None) or []):
            if str(artifact.id) == str(artifact_id) and str(artifact.artifact_type) == artifact_type:
                if str(artifact.status or "") != ArtifactStatus.AVAILABLE.value:
                    raise ValidationAppError(f"{artifact_type} artifact is not available")
                return artifact
        raise ValidationAppError(f"{artifact_type} artifact is not attached to the revision")

    def _record_rvc_vocal_artifact(
        self,
        db: Session,
        *,
        revision: ScoreRevision,
        source_artifact: Artifact,
        payload: bytes,
        content_type: str,
        spec: RvcJobSpec,
        response_metadata: dict[str, Any],
        task_id: str | None,
    ) -> Artifact:
        if not payload:
            raise ValidationAppError("external RVC service returned an empty vocal artifact")
        workspace = ProjectWorkspace(project_id=str(revision.project_id))
        output_dir = workspace.revision_dir(str(revision.id)) / "rvc"
        output_dir.mkdir(parents=True, exist_ok=True)
        suffix = self._suffix_for_content_type(content_type)
        output_path = output_dir / f"rvc_vocal_{int(time.time())}{suffix}"
        output_path.write_bytes(payload)
        artifact = Artifact(
            project_id=revision.project_id,
            score_id=revision.score_id,
            score_revision_id=revision.id,
            task_id=uuid.UUID(str(task_id)) if task_id else None,
            artifact_type=ArtifactType.RVC_VOCAL.value,
            status=ArtifactStatus.AVAILABLE.value,
            storage_backend=ArtifactStorageBackend.WORKSPACE.value,
            storage_path=str(output_path),
            filename=output_path.name,
            mime_type=content_type.split(";", 1)[0].strip() or "audio/wav",
            file_size_bytes=len(payload),
            checksum=hashlib.sha256(payload).hexdigest(),
            artifact_metadata={
                "mode": "voice_conversion",
                "rvc_backend": str(spec.rvc_backend or "external"),
                "voice_model_id": spec.voice_model_id,
                "transpose_semitones": int(spec.transpose_semitones),
                "source_vocal_stem_artifact_id": str(source_artifact.id),
                "score_guided": False,
                "response": dict(response_metadata or {}),
            },
        )
        db.add(artifact)
        return artifact

    @staticmethod
    def _suffix_for_content_type(content_type: str) -> str:
        normalized = str(content_type or "").split(";", 1)[0].strip().lower()
        if normalized in {"audio/mpeg", "audio/mp3"}:
            return ".mp3"
        if normalized in {"audio/flac", "audio/x-flac"}:
            return ".flac"
        return ".wav"
