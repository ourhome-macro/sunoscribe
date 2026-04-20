import uuid

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.services.auth_service import is_token_revoked
from app.utils.errors import AuthenticationError
from app.utils.security import decode_token

bearer_scheme = HTTPBearer(auto_error=False)


def get_bearer_token(credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)) -> str:
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("缺少认证信息")
    return credentials.credentials


def get_current_user(
    token: str = Depends(get_bearer_token),
    db: Session = Depends(get_db),
) -> User:
    payload = decode_token(token)
    if payload.get("type") != "access":
        raise AuthenticationError("Token 类型错误")

    user_id = payload.get("sub")
    if not user_id:
        raise AuthenticationError("Token 缺少用户信息")
    jti = str(payload.get("jti") or "").strip()
    if not jti:
        raise AuthenticationError("Token 缺少 jti")
    if is_token_revoked(db, jti=jti, token_type="access"):
        raise AuthenticationError("access token 已失效")

    try:
        user_uuid = uuid.UUID(str(user_id))
    except (TypeError, ValueError) as exc:
        raise AuthenticationError("Token 用户标识无效") from exc

    user = db.get(User, user_uuid)
    if not user:
        raise AuthenticationError("用户不存在")

    return user
