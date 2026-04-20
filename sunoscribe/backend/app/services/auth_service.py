import uuid
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models.token_revocation import TokenRevocation
from app.models.user import User
from app.models.user_settings import UserSettings
from app.utils.errors import AuthenticationError, ValidationAppError
from app.utils.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def register_user(db: Session, username: str, email: str, password: str) -> User:
    exists_stmt = select(User).where(or_(User.username == username, User.email == email))
    exists_user = db.execute(exists_stmt).scalar_one_or_none()
    if exists_user:
        raise ValidationAppError("用户名或邮箱已存在")

    user = User(username=username, email=email, password_hash=hash_password(password))
    try:
        db.add(user)
        db.flush()

        settings_row = UserSettings(user_id=user.id)
        db.add(settings_row)

        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ValidationAppError("用户名或邮箱已存在") from exc
    db.refresh(user)
    return user


def login(db: Session, username_or_email: str, password: str) -> dict:
    stmt = select(User).where(or_(User.username == username_or_email, User.email == username_or_email))
    user = db.execute(stmt).scalar_one_or_none()
    if not user or not verify_password(password, user.password_hash):
        raise AuthenticationError("用户名/邮箱或密码错误")

    user_id = str(user.id)
    return {
        "access_token": create_access_token(user_id),
        "refresh_token": create_refresh_token(user_id),
        "token_type": "bearer",
        "expires_in": settings.access_token_expire_minutes * 60,
    }


def refresh_access_token(db: Session, refresh_token: str) -> dict:
    payload = decode_token(refresh_token)
    if payload.get("type") != "refresh":
        raise AuthenticationError("仅支持 refresh token 刷新")

    user_uuid = _extract_user_uuid(payload)
    _ensure_user_exists(db, user_uuid)
    jti = _extract_jti(payload)
    expires_at = _extract_exp(payload)

    # Rotation: once a refresh token is used, revoke its jti immediately.
    # Concurrent reuse will hit the unique constraint and be rejected.
    _revoke_refresh_jti(
        db,
        jti=jti,
        user_id=user_uuid,
        expires_at=expires_at,
        fail_if_exists=True,
    )

    user_id = str(user_uuid)
    return {
        "access_token": create_access_token(user_id),
        "refresh_token": create_refresh_token(user_id),
        "token_type": "bearer",
        "expires_in": settings.access_token_expire_minutes * 60,
    }


def logout(db: Session, refresh_token: str | None) -> None:
    if not refresh_token:
        return
    payload = decode_token(refresh_token)
    if payload.get("type") != "refresh":
        return
    user_uuid = _extract_user_uuid(payload)
    jti = _extract_jti(payload)
    expires_at = _extract_exp(payload)
    _revoke_refresh_jti(
        db,
        jti=jti,
        user_id=user_uuid,
        expires_at=expires_at,
        fail_if_exists=False,
    )


def _extract_user_uuid(payload: dict) -> uuid.UUID:
    raw_user_id = payload.get("sub")
    if not raw_user_id:
        raise AuthenticationError("token 缺少用户信息")
    try:
        return uuid.UUID(str(raw_user_id))
    except (TypeError, ValueError) as exc:
        raise AuthenticationError("token 用户标识无效") from exc


def _extract_jti(payload: dict) -> str:
    jti = str(payload.get("jti") or "").strip()
    if not jti:
        raise AuthenticationError("refresh token 缺少 jti")
    return jti


def _extract_exp(payload: dict) -> datetime | None:
    exp = payload.get("exp")
    if isinstance(exp, datetime):
        return exp if exp.tzinfo else exp.replace(tzinfo=timezone.utc)
    if isinstance(exp, (int, float)):
        try:
            return datetime.fromtimestamp(float(exp), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    return None


def _ensure_user_exists(db: Session, user_id: uuid.UUID) -> None:
    if not db.get(User, user_id):
        raise AuthenticationError("用户不存在")


def _revoke_refresh_jti(
    db: Session,
    *,
    jti: str,
    user_id: uuid.UUID,
    expires_at: datetime | None,
    fail_if_exists: bool,
) -> None:
    db.add(
        TokenRevocation(
            jti=jti,
            token_type="refresh",
            user_id=user_id,
            expires_at=expires_at,
        )
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if fail_if_exists:
            raise AuthenticationError("refresh token 已失效") from exc
