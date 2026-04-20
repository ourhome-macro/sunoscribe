import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import ScoreType


class GenerateScoreRequest(BaseModel):
    score_type: ScoreType = ScoreType.JIANPU
    key: str = Field(default="C Major", max_length=50)


class UpdateScoreRequest(BaseModel):
    score_type: ScoreType | None = None
    key: str | None = Field(default=None, max_length=50)
    vocal_range: str | None = Field(default=None, max_length=100)
    recommended_voice: str | None = Field(default=None, max_length=100)
    emotion: str | None = Field(default=None, max_length=100)
    score_data: dict[str, Any] | None = None


class ScoreDTO(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    score_type: str
    key: str
    vocal_range: str | None = None
    recommended_voice: str | None = None
    emotion: str | None = None
    score_data: dict[str, Any]
    created_at: datetime
    updated_at: datetime
