from sqlalchemy.orm import Session

from app.models.user import User
from app.models.user_settings import UserSettings
from app.utils.errors import ValidationAppError


ALLOWED_SCORE_TYPES = {"jianpu", "staff"}


def get_or_create_settings(db: Session, user: User) -> UserSettings:
    settings = user.settings
    if settings:
        return settings

    settings = UserSettings(user_id=user.id)
    db.add(settings)
    db.commit()
    db.refresh(settings)
    return settings


def update_profile(db: Session, user: User, username: str | None, avatar_url: str | None) -> User:
    if username and username != user.username:
        exists = db.query(User).filter(User.username == username).first()
        if exists:
            raise ValidationAppError("用户名已存在")
        user.username = username

    if avatar_url is not None:
        user.avatar_url = avatar_url

    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_settings(
    db: Session,
    user: User,
    default_score_type: str | None,
    default_key: str | None,
    api_keys: dict | None,
) -> UserSettings:
    settings = get_or_create_settings(db, user)

    if default_score_type is not None:
        if default_score_type not in ALLOWED_SCORE_TYPES:
            raise ValidationAppError("default_score_type 必须是 jianpu 或 staff")
        settings.default_score_type = default_score_type

    if default_key is not None:
        settings.default_key = default_key

    if api_keys is not None:
        settings.api_keys = api_keys

    db.add(settings)
    db.commit()
    db.refresh(settings)
    return settings
