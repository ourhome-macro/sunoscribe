from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.task_orchestrator import task_orchestrator
from app.services.task_service import get_task_status_by_id, retry_task as retry_task_service, task_to_dict
from app.utils.dependencies import get_current_user
from app.utils.responses import success_response

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("/{task_id}")
def get_task_status_api(
    task_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    task = get_task_status_by_id(db, user=current_user, task_id=task_id)
    return success_response(_serialize_task(task))


@router.post("/{task_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry_task_api(
    task_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    task = retry_task_service(db, user=current_user, task_id=task_id)
    task_orchestrator.enqueue(str(task.id))
    return success_response(_serialize_task(task_to_dict(task)), "任务已重新入队")


def _serialize_task(task: dict) -> dict:
    return {
        "task_id": str(task["task_id"]),
        "project_id": str(task["project_id"]),
        "task_type": task["task_type"],
        "status": task["status"],
        "progress": int(task["progress"]),
        "retry_count": int(task["retry_count"]),
        "max_retries": int(task["max_retries"]),
        "can_retry": bool(task["can_retry"]),
        "error_message": task["error_message"],
        "result_payload": task["result_payload"] if isinstance(task.get("result_payload"), dict) else {},
        "queued_at": task["queued_at"].isoformat() if task.get("queued_at") else None,
        "started_at": task["started_at"].isoformat() if task.get("started_at") else None,
        "finished_at": task["finished_at"].isoformat() if task.get("finished_at") else None,
    }
