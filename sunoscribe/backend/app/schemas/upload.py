import uuid

from pydantic import BaseModel, Field


class UploadResponse(BaseModel):
    file_path: str
    project_id: uuid.UUID
    filename: str
    size: int = Field(ge=0)
    artifact_id: uuid.UUID | None = None
