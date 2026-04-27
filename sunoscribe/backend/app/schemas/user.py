import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class UserProfile(BaseModel):
    id: uuid.UUID
    username: str
    email: EmailStr
    avatar_url: str | None = None
    created_at: datetime
    updated_at: datetime


class UpdateMeRequest(BaseModel):
    username: str | None = Field(default=None, min_length=3, max_length=50)
    avatar_url: str | None = Field(default=None, max_length=500)


class UserSettingsDTO(BaseModel):
    default_score_type: str
    default_key: str
    api_keys: dict[str, dict[str, bool]] = Field(default_factory=dict)


class UpdateSettingsRequest(BaseModel):
    default_score_type: str | None = None
    default_key: str | None = None
    api_keys: dict[str, str] | None = None
