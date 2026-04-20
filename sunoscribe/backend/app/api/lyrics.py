from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.lyrics import UpdateLyricsRequest
from app.services.lyrics_service import get_lyrics_by_project_id, update_lyrics
from app.utils.dependencies import get_current_user
from app.utils.responses import success_response

router = APIRouter(tags=["lyrics"])


@router.get("/projects/{project_id}/lyrics")
def get_project_lyrics_api(
    project_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    lyrics = get_lyrics_by_project_id(db, user=current_user, project_id=project_id)
    return success_response(
        {
            "id": str(lyrics.id),
            "project_id": str(lyrics.project_id),
            "text": lyrics.text,
            "timeline": lyrics.timeline,
            "created_at": lyrics.created_at.isoformat(),
            "updated_at": lyrics.updated_at.isoformat(),
        }
    )


@router.put("/lyrics/{lyrics_id}")
def update_lyrics_api(
    lyrics_id: str,
    payload: UpdateLyricsRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    lyrics = update_lyrics(
        db,
        user=current_user,
        lyrics_id=lyrics_id,
        text=payload.text,
        timeline=payload.timeline,
    )
    return success_response(
        {
            "id": str(lyrics.id),
            "project_id": str(lyrics.project_id),
            "text": lyrics.text,
            "timeline": lyrics.timeline,
            "created_at": lyrics.created_at.isoformat(),
            "updated_at": lyrics.updated_at.isoformat(),
        },
        "歌词更新成功",
    )
