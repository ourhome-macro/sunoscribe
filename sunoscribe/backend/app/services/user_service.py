import base64
import hashlib
import json
from typing import Any

from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings as app_settings
from app.models.user import User
from app.models.user_settings import UserSettings
from app.utils.errors import ValidationAppError


ALLOWED_SCORE_TYPES = {"jianpu", "staff"}
ENCRYPTED_API_KEYS_MARKER = "_sunoscribe_encrypted_api_keys"


def get_or_create_settings(db: Session, user: User) -> UserSettings:
    settings = user.settings
    if settings:
        return settings

    settings = UserSettings(user_id=user.id)
    db.add(settings)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        settings = user.settings
        if settings:
            return settings
        raise
    db.refresh(settings)
    return settings


def update_profile(db: Session, user: User, username: str | None, avatar_url: str | None) -> User:
    if username and username != user.username:
        exists_stmt = select(User.id).where(User.username == username, User.id != user.id)
        exists = db.execute(exists_stmt).scalar_one_or_none()
        if exists:
            raise ValidationAppError("用户名已存在")
        user.username = username

    if avatar_url is not None:
        user.avatar_url = avatar_url

    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ValidationAppError("用户名已存在") from exc
    db.refresh(user)
    return user


def update_settings(
    db: Session,
    user: User,
    default_score_type: str | None,
    default_key: str | None,
    api_keys: dict[str, str] | None,
) -> UserSettings:
    settings = get_or_create_settings(db, user)

    if default_score_type is not None:
        if default_score_type not in ALLOWED_SCORE_TYPES:
            raise ValidationAppError("default_score_type 必须是 jianpu 或 staff")
        settings.default_score_type = default_score_type

    if default_key is not None:
        settings.default_key = default_key

    if api_keys is not None:
        settings.api_keys = encrypt_api_keys(api_keys)

    db.add(settings)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ValidationAppError("用户设置更新失败，请稍后重试") from exc
    db.refresh(settings)
    return settings


def summarize_api_keys(stored_api_keys: dict | None) -> dict[str, dict[str, bool]]:
    if not isinstance(stored_api_keys, dict) or not stored_api_keys:
        return {}

    if stored_api_keys.get(ENCRYPTED_API_KEYS_MARKER) is True:
        decrypted = decrypt_api_keys(stored_api_keys)
    else:
        decrypted = stored_api_keys

    summary: dict[str, dict[str, bool]] = {}
    for key, value in decrypted.items():
        name = str(key).strip()
        if not name:
            continue
        summary[name] = {"configured": bool(str(value or "").strip())}
    return summary


def encrypt_api_keys(api_keys: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(api_keys, dict):
        raise ValidationAppError("api_keys must be an object")

    sanitized: dict[str, str] = {}
    for key, value in api_keys.items():
        name = str(key).strip()
        if not name:
            raise ValidationAppError("api_keys contains an empty key name")
        sanitized[name] = str(value or "")

    if not sanitized:
        return {}

    payload = json.dumps(sanitized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    token = _api_keys_fernet().encrypt(payload).decode("ascii")
    return {ENCRYPTED_API_KEYS_MARKER: True, "v": 1, "token": token}


def decrypt_api_keys(stored_api_keys: dict[str, Any]) -> dict[str, str]:
    token = str(stored_api_keys.get("token") or "").strip()
    if not token:
        raise ValidationAppError("api_keys encrypted payload is missing")
    try:
        raw = _api_keys_fernet().decrypt(token.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ValidationAppError("api_keys encrypted payload is invalid") from exc
    if not isinstance(payload, dict):
        raise ValidationAppError("api_keys encrypted payload must be an object")
    return {str(key): str(value or "") for key, value in payload.items()}


def _api_keys_fernet() -> Fernet:
    key_material = str(app_settings.api_keys_encryption_key or "").encode("utf-8")
    if not key_material:
        raise ValidationAppError("api key encryption key is not configured")
    digest = hashlib.sha256(key_material).digest()
    return Fernet(base64.urlsafe_b64encode(digest))
