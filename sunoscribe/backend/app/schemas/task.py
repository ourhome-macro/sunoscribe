import uuid

from pydantic import BaseModel, Field


class TaskStatusDTO(BaseModel):
    task_id: uuid.UUID
    project_id: uuid.UUID
    status: str
    progress: int = Field(ge=0, le=100)
