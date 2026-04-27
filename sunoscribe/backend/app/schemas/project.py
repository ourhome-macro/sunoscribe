import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ProjectStatus, SourceType


class CreateProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    source_type: SourceType = SourceType.UPLOAD
    source_url: str | None = Field(default=None, max_length=2000)


class UpdateProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    source_url: str | None = Field(default=None, max_length=2000)
    status: ProjectStatus | None = None
    progress: int | None = Field(default=None, ge=0, le=100)


class ProjectDTO(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    source_type: str
    source_url: str | None = None
    audio_path: str | None = None
    status: str
    progress: int
    created_at: datetime
    updated_at: datetime
