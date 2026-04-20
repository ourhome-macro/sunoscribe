import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TaskStatusDTO(BaseModel):
    task_id: uuid.UUID
    project_id: uuid.UUID
    task_type: str
    status: str
    progress: int = Field(ge=0, le=100)
    retry_count: int = Field(ge=0)
    max_retries: int = Field(ge=0)
    can_retry: bool
    error_message: str | None = None
    result_payload: dict[str, Any] = Field(default_factory=dict)
    queued_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class TaskCreateDTO(BaseModel):
    task_id: uuid.UUID
    project_id: uuid.UUID
    task_type: str
    status: str
    progress: int = Field(ge=0, le=100)
    retry_count: int = Field(ge=0)
    max_retries: int = Field(ge=0)
    can_retry: bool = False
    error_message: str | None = None
    queued_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
