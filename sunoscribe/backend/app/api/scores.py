from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.score import GenerateScoreRequest, UpdateScoreRequest
from app.services.score_service import export_score, generate_or_regenerate_score, get_score_by_project_id, update_score
from app.utils.dependencies import get_current_user
from app.utils.responses import success_response

router = APIRouter(tags=["scores"])


@router.get("/projects/{project_id}/score")
def get_project_score_api(
    project_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    score = get_score_by_project_id(db, user=current_user, project_id=project_id)
    return success_response(
        {
            "id": str(score.id),
            "project_id": str(score.project_id),
            "score_type": score.score_type,
            "key": score.key,
            "vocal_range": score.vocal_range,
            "recommended_voice": score.recommended_voice,
            "emotion": score.emotion,
            "score_data": score.score_data,
            "created_at": score.created_at.isoformat(),
            "updated_at": score.updated_at.isoformat(),
        }
    )


@router.post("/projects/{project_id}/score")
def regenerate_project_score_api(
    project_id: str,
    payload: GenerateScoreRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    score = generate_or_regenerate_score(
        db,
        user=current_user,
        project_id=project_id,
        score_type=payload.score_type,
        key=payload.key,
    )
    return success_response(
        {
            "id": str(score.id),
            "project_id": str(score.project_id),
            "score_type": score.score_type,
            "key": score.key,
            "vocal_range": score.vocal_range,
            "recommended_voice": score.recommended_voice,
            "emotion": score.emotion,
            "score_data": score.score_data,
            "created_at": score.created_at.isoformat(),
            "updated_at": score.updated_at.isoformat(),
        },
        "谱子生成成功",
    )


@router.put("/scores/{score_id}")
def update_score_api(
    score_id: str,
    payload: UpdateScoreRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    score = update_score(
        db,
        user=current_user,
        score_id=score_id,
        score_type=payload.score_type,
        key=payload.key,
        vocal_range=payload.vocal_range,
        recommended_voice=payload.recommended_voice,
        emotion=payload.emotion,
        score_data=payload.score_data,
    )
    return success_response(
        {
            "id": str(score.id),
            "project_id": str(score.project_id),
            "score_type": score.score_type,
            "key": score.key,
            "vocal_range": score.vocal_range,
            "recommended_voice": score.recommended_voice,
            "emotion": score.emotion,
            "score_data": score.score_data,
            "created_at": score.created_at.isoformat(),
            "updated_at": score.updated_at.isoformat(),
        },
        "谱子更新成功",
    )


@router.get("/scores/{score_id}/export")
def export_score_api(
    score_id: str,
    format: str = Query(default="midi"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    content, media_type, filename = export_score(
        db,
        user=current_user,
        score_id=score_id,
        export_format=format,
    )
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(content=content, media_type=media_type, headers=headers)
