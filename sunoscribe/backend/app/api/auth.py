from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    LogoutRequest,
    RefreshTokenRequest,
    RegisterRequest,
    ResetPasswordRequest,
)
from app.services.auth_service import (
    create_password_reset_token,
    login,
    logout,
    refresh_access_token,
    register_user,
    reset_password_with_token,
)
from app.utils.dependencies import get_bearer_token
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
def logout_api(
    payload: LogoutRequest,
    db: Session = Depends(get_db),
    access_token: str = Depends(get_bearer_token),
):
    logout(db, access_token, payload.refresh_token)
    return success_response({"logged_out": True}, "登出成功")


@router.post("/forgot-password")
def forgot_password_api(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    reset_token = create_password_reset_token(db, email=payload.email)
    # Production should send token by email; keep response generic to avoid user enumeration.
    return success_response(
        {
            "sent": True,
            "reset_token": reset_token if reset_token and settings.app_env != "production" else None,
        },
        "如果邮箱存在，将发送重置链接",
    )


@router.post("/reset-password")
def reset_password_api(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    reset_password_with_token(db, reset_token=payload.reset_token, new_password=payload.new_password)
    return success_response({"reset": True}, "密码重置成功")
