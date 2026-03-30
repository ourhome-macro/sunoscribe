import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import settings
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

_revoked_refresh_jti: set[str] = set()


def register_user(db: Session, username: str, email: str, password: str) -> User:
    exists_stmt = select(User).where(or_(User.username == username, User.email == email))
    exists_user = db.execute(exists_stmt).scalar_one_or_none()
    if exists_user:
        raise ValidationAppError("用户名或邮箱已存在")

    user = User(username=username, email=email, password_hash=hash_password(password))
    db.add(user)
    db.flush()

    settings_row = UserSettings(user_id=user.id)
    db.add(settings_row)

    db.commit()
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


def refresh_access_token(refresh_token: str) -> dict:
    payload = decode_token(refresh_token)
    if payload.get("type") != "refresh":
        raise AuthenticationError("仅支持 refresh token 刷新")

    jti = payload.get("jti")
    if jti in _revoked_refresh_jti:
        raise AuthenticationError("refresh token 已失效")

    user_id = payload.get("sub")
    if not user_id:
        raise AuthenticationError("token 缺少用户信息")

    return {
        "access_token": create_access_token(user_id),
        "refresh_token": create_refresh_token(user_id),
        "token_type": "bearer",
        "expires_in": settings.access_token_expire_minutes * 60,
    }


def logout(refresh_token: str | None) -> None:
    if not refresh_token:
        return
    payload = decode_token(refresh_token)
    if payload.get("type") != "refresh":
        return
    jti = payload.get("jti")
    if jti:
        _revoked_refresh_jti.add(jti)
