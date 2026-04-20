from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.auth import LoginRequest, LogoutRequest, RefreshTokenRequest, RegisterRequest
from app.services.auth_service import login, logout, refresh_access_token, register_user
from app.utils.responses import success_response

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    user = register_user(db, payload.username, payload.email, payload.password)
    return success_response(
        {
            "id": str(user.id),
            "username": user.username,
            "email": user.email,
            "avatar_url": user.avatar_url,
        },
        "注册成功",
    )


@router.post("/login")
def login_api(payload: LoginRequest, db: Session = Depends(get_db)):
    tokens = login(db, payload.username_or_email, payload.password)
    return success_response(tokens, "登录成功")


@router.post("/refresh")
def refresh_api(payload: RefreshTokenRequest, db: Session = Depends(get_db)):
    tokens = refresh_access_token(db, payload.refresh_token)
    return success_response(tokens, "刷新成功")


@router.post("/logout")
def logout_api(payload: LogoutRequest, db: Session = Depends(get_db)):
    logout(db, payload.refresh_token)
    return success_response({"logged_out": True}, "登出成功")
