import logging
import secrets
import smtplib
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any
from urllib.parse import urlencode

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

logger = logging.getLogger(__name__)

try:
    from redis import Redis
except Exception:  # pragma: no cover - optional dependency/runtime
    Redis = None

_redis_client: Any = None
_redis_init_attempted = False
PASSWORD_RESET_TTL_SECONDS = 30 * 60


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

    if is_token_revoked(db, jti=jti, token_type="refresh"):
        raise AuthenticationError("refresh token 已失效")

    # Rotation: old refresh token must become unusable immediately.
    _revoke_token_jti(
        db,
        jti=jti,
        token_type="refresh",
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


def logout(db: Session, access_token: str, refresh_token: str | None) -> None:
    access_payload = decode_token(access_token)
    if access_payload.get("type") != "access":
        raise AuthenticationError("仅支持 access token 登出")

    user_uuid = _extract_user_uuid(access_payload)
    access_jti = _extract_jti(access_payload)
    access_exp = _extract_exp(access_payload)

    # Proactive access-token revocation.
    _revoke_token_jti(
        db,
        jti=access_jti,
        token_type="access",
        user_id=user_uuid,
        expires_at=access_exp,
        fail_if_exists=False,
    )

    if refresh_token is None:
        return

    refresh_payload = decode_token(refresh_token)
    if refresh_payload.get("type") != "refresh":
        raise AuthenticationError("refresh token 类型错误")

    refresh_user_uuid = _extract_user_uuid(refresh_payload)
    if refresh_user_uuid != user_uuid:
        raise AuthenticationError("refresh token 与当前用户不匹配")

    refresh_jti = _extract_jti(refresh_payload)
    refresh_exp = _extract_exp(refresh_payload)
    _revoke_token_jti(
        db,
        jti=refresh_jti,
        token_type="refresh",
        user_id=refresh_user_uuid,
        expires_at=refresh_exp,
        fail_if_exists=False,
    )


def create_password_reset_token(db: Session, *, email: str) -> str | None:
    _require_redis_client_for_password_reset()
    if settings.app_env == "production":
        _validate_password_reset_email_config()

    stmt = select(User).where(User.email == email)
    user = db.execute(stmt).scalar_one_or_none()
    if user is None:
        return None

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=PASSWORD_RESET_TTL_SECONDS)
    _store_password_reset_token(token=token, user_id=user.id, expires_at=expires_at)
    if settings.app_env == "production":
        _send_password_reset_email(email=user.email, token=token)
        return None
    return token


def reset_password_with_token(db: Session, *, reset_token: str, new_password: str) -> None:
    user_id = _consume_password_reset_token(reset_token)
    user = db.get(User, user_id)
    if user is None:
        raise ValidationAppError("重置令牌无效或已过期")

    user.password_hash = hash_password(new_password)
    db.add(user)
    db.commit()


def is_token_revoked(db: Session, *, jti: str, token_type: str) -> bool:
    if _is_token_revoked_in_redis(jti=jti, token_type=token_type):
        return True

    stmt = select(TokenRevocation.id).where(
        TokenRevocation.jti == jti,
        TokenRevocation.token_type == token_type,
    )
    revoked = db.execute(stmt).scalar_one_or_none() is not None
    if revoked:
        _set_revocation_cache(jti=jti, token_type=token_type, expires_at=None)
    return revoked


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
        raise AuthenticationError("token 缺少 jti")
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


def _revoke_token_jti(
    db: Session,
    *,
    jti: str,
    token_type: str,
    user_id: uuid.UUID,
    expires_at: datetime | None,
    fail_if_exists: bool,
) -> None:
    db.add(
        TokenRevocation(
            jti=jti,
            token_type=token_type,
            user_id=user_id,
            expires_at=expires_at,
        )
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if fail_if_exists:
            raise AuthenticationError(f"{token_type} token 已失效") from exc

    _set_revocation_cache(jti=jti, token_type=token_type, expires_at=expires_at)


def _set_revocation_cache(*, jti: str, token_type: str, expires_at: datetime | None) -> None:
    client = _get_redis_client()
    if client is None:
        return

    ttl = _revocation_ttl_seconds(expires_at)
    key = _revocation_key(token_type=token_type, jti=jti)
    try:
        client.set(key, "1", ex=ttl)
    except Exception as exc:  # pragma: no cover - runtime infrastructure error
        logger.warning("Failed to set token revocation in redis: %s", exc)


def _is_token_revoked_in_redis(*, jti: str, token_type: str) -> bool:
    client = _get_redis_client()
    if client is None:
        return False

    key = _revocation_key(token_type=token_type, jti=jti)
    try:
        return bool(client.exists(key))
    except Exception as exc:  # pragma: no cover - runtime infrastructure error
        logger.warning("Failed to query token revocation in redis: %s", exc)
        return False


def _revocation_ttl_seconds(expires_at: datetime | None) -> int:
    if expires_at is not None:
        now = datetime.now(timezone.utc)
        delta = int((expires_at - now).total_seconds())
        if delta > 0:
            return delta

    # Fallback TTL for malformed/expired token payloads.
    return max(60, int(timedelta(days=settings.refresh_token_expire_days).total_seconds()))


def _revocation_key(*, token_type: str, jti: str) -> str:
    return f"sunoscribe:auth:revoked:{token_type}:{jti}"


def _get_redis_client() -> Any | None:
    global _redis_client, _redis_init_attempted

    if _redis_init_attempted:
        return _redis_client
    _redis_init_attempted = True

    if not settings.redis_url or Redis is None:
        return None

    try:
        client = Redis.from_url(settings.redis_url, decode_responses=True)
        client.ping()
        _redis_client = client
    except Exception as exc:  # pragma: no cover - runtime infrastructure error
        logger.warning("Redis unavailable; token revocation will use DB lookup: %s", exc)
        _redis_client = None

    return _redis_client


def _store_password_reset_token(*, token: str, user_id: uuid.UUID, expires_at: datetime) -> None:
    client = _require_redis_client_for_password_reset()
    key = _password_reset_key(token)
    ttl = max(60, int((expires_at - datetime.now(timezone.utc)).total_seconds()))
    try:
        client.set(key, str(user_id), ex=ttl)
    except Exception as exc:  # pragma: no cover - runtime infrastructure error
        raise ValidationAppError("password reset token storage is unavailable") from exc


def _consume_password_reset_token(token: str) -> uuid.UUID:
    raw = str(token or "").strip()
    if not raw:
        raise ValidationAppError("reset_token 不能为空")

    client = _require_redis_client_for_password_reset()
    key = _password_reset_key(raw)
    try:
        user_id_raw = client.get(key)
        if user_id_raw:
            client.delete(key)
            return uuid.UUID(str(user_id_raw))
    except Exception as exc:  # pragma: no cover - runtime infrastructure error
        raise ValidationAppError("password reset token storage is unavailable") from exc

    raise ValidationAppError("重置令牌无效或已过期")


def _require_redis_client_for_password_reset() -> Any:
    client = _get_redis_client()
    if client is None:
        raise ValidationAppError("password reset requires Redis configuration")
    return client


def _send_password_reset_email(*, email: str, token: str) -> None:
    base_url, smtp_host, from_email = _validate_password_reset_email_config()

    separator = "&" if "?" in base_url else "?"
    reset_link = f"{base_url}{separator}{urlencode({'token': token})}"

    message = EmailMessage()
    message["Subject"] = "Reset your SunoScribe password"
    message["From"] = from_email
    message["To"] = email
    message.set_content(
        "Use the following link to reset your SunoScribe password. "
        f"This link expires in {PASSWORD_RESET_TTL_SECONDS // 60} minutes.\n\n{reset_link}\n"
    )

    try:
        with smtplib.SMTP(smtp_host, int(settings.smtp_port), timeout=15) as smtp:
            if settings.smtp_use_tls:
                smtp.starttls()
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password or "")
            smtp.send_message(message)
    except Exception as exc:  # pragma: no cover - runtime infrastructure error
        raise ValidationAppError("failed to send password reset email") from exc


def _validate_password_reset_email_config() -> tuple[str, str, str]:
    base_url = str(settings.password_reset_base_url or "").strip()
    smtp_host = str(settings.smtp_host or "").strip()
    from_email = str(settings.smtp_from_email or "").strip()
    if not base_url or not smtp_host or not from_email:
        raise ValidationAppError("password reset email is not configured")
    return base_url, smtp_host, from_email


def _password_reset_key(token: str) -> str:
    return f"sunoscribe:auth:pwdreset:{token}"
