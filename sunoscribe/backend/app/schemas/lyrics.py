import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class UpdateLyricsRequest(BaseModel):
    text: str | None = None
    timeline: list[Any] | dict[str, Any] | None = None


class LyricsDTO(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    text: str
    timeline: list[Any] | dict[str, Any]
    created_at: datetime
    updated_at: datetime
