import uuid

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.utils.errors import AuthenticationError
from app.utils.security import decode_token

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("缺少认证信息")

    payload = decode_token(credentials.credentials)
    if payload.get("type") != "access":
        raise AuthenticationError("Token 类型错误")

    user_id = payload.get("sub")
    if not user_id:
        raise AuthenticationError("Token 缺少用户信息")

    try:
        user_uuid = uuid.UUID(str(user_id))
    except (TypeError, ValueError) as exc:
        raise AuthenticationError("Token 用户标识无效") from exc

    user = db.get(User, user_uuid)
    if not user:
        raise AuthenticationError("用户不存在")

    return user
