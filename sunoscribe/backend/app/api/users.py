from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.user import UpdateMeRequest, UpdateSettingsRequest
from app.services.user_service import get_or_create_settings, summarize_api_keys, update_profile, update_settings
from app.utils.dependencies import get_current_user
from app.utils.responses import success_response

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me")
def get_me(current_user=Depends(get_current_user)):
    return success_response(
        {
            "id": str(current_user.id),
            "username": current_user.username,
            "email": current_user.email,
            "avatar_url": current_user.avatar_url,
            "created_at": current_user.created_at.isoformat(),
            "updated_at": current_user.updated_at.isoformat(),
        }
    )


@router.put("/me")
def update_me(
    payload: UpdateMeRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    user = update_profile(db, current_user, payload.username, payload.avatar_url)
    return success_response(
        {
            "id": str(user.id),
            "username": user.username,
            "email": user.email,
            "avatar_url": user.avatar_url,
            "created_at": user.created_at.isoformat(),
            "updated_at": user.updated_at.isoformat(),
        },
        "更新成功",
    )


@router.get("/me/settings")
def get_me_settings(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    settings = get_or_create_settings(db, current_user)
    return success_response(
        {
            "default_score_type": settings.default_score_type,
            "default_key": settings.default_key,
            "api_keys": summarize_api_keys(settings.api_keys),
        }
    )


@router.put("/me/settings")
def update_me_settings(
    payload: UpdateSettingsRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    settings = update_settings(
        db,
        current_user,
        default_score_type=payload.default_score_type,
        default_key=payload.default_key,
        api_keys=payload.api_keys,
    )
    return success_response(
        {
            "default_score_type": settings.default_score_type,
            "default_key": settings.default_key,
            "api_keys": summarize_api_keys(settings.api_keys),
        },
        "设置更新成功",
    )
