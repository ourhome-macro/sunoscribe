from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.task_service import get_task_status_by_id
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
    return success_response(
        {
            "task_id": str(task["task_id"]),
            "project_id": str(task["project_id"]),
            "status": task["status"],
            "progress": task["progress"],
        }
    )
