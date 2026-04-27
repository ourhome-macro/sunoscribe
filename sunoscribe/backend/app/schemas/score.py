import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import ScoreType
from app.schemas.score_patch import ScorePatch


class GenerateScoreRequest(BaseModel):
    score_type: ScoreType = ScoreType.JIANPU
    key: str = Field(default="C Major", max_length=50)


class UpdateScoreRequest(BaseModel):
    score_type: ScoreType | None = None
    key: str | None = Field(default=None, max_length=50)
    vocal_range: str | None = Field(default=None, max_length=100)
    recommended_voice: str | None = Field(default=None, max_length=100)
    emotion: str | None = Field(default=None, max_length=100)
    revision_id: uuid.UUID | None = None
    patch: ScorePatch | None = None


class ScoreDTO(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    score_type: str
    key: str
    vocal_range: str | None = None
    recommended_voice: str | None = None
    emotion: str | None = None
    score_data: dict[str, Any]
    current_revision_id: uuid.UUID | None = None
    current_revision: dict[str, Any] | None = None
    revisions: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
