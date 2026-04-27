from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.score import GenerateScoreRequest, UpdateScoreRequest
from app.services.score_service import build_score_response, export_score, get_score_by_project_id, update_score
from app.services.task_orchestrator import task_orchestrator
from app.services.task_service import create_score_generation_task
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
    return success_response(build_score_response(score))


@router.post("/projects/{project_id}/score", status_code=status.HTTP_202_ACCEPTED)
def regenerate_project_score_api(
    project_id: str,
    payload: GenerateScoreRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    task = create_score_generation_task(
        db,
        user=current_user,
        project_id=project_id,
        score_type=payload.score_type.value,
        key=payload.key,
    )
    task_orchestrator.enqueue(str(task.id))

    return success_response(
        {
            "task_id": str(task.id),
            "project_id": str(task.project_id),
            "task_type": task.task_type,
            "status": task.status,
            "progress": int(task.progress),
            "retry_count": int(task.retry_count),
            "max_retries": int(task.max_retries),
            "can_retry": False,
            "error_message": task.error_message,
            "queued_at": task.queued_at.isoformat() if task.queued_at else None,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "finished_at": task.finished_at.isoformat() if task.finished_at else None,
        },
        "score generation task queued",
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
        patch=payload.patch,
        revision_id=str(payload.revision_id) if payload.revision_id else None,
    )
    return success_response(build_score_response(score), "score updated")


@router.get("/scores/{score_id}/export")
def export_score_api(
    score_id: str,
    format: str = Query(default="midi"),
    revision_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    content, media_type, filename = export_score(
        db,
        user=current_user,
        score_id=score_id,
        export_format=format,
        revision_id=revision_id,
    )
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(content=content, media_type=media_type, headers=headers)
