from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.project import CreateProjectRequest, UpdateProjectRequest
from app.services.project_service import (
    create_project,
    delete_project,
    get_project_by_id,
    list_projects,
    update_project,
)
from app.utils.dependencies import get_current_user
from app.utils.responses import paginated_response, success_response

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("")
def create_project_api(
    payload: CreateProjectRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    project = create_project(
        db,
        user=current_user,
        name=payload.name,
        source_type=payload.source_type,
        source_url=payload.source_url,
        audio_path=payload.audio_path,
    )
    return success_response(
        {
            "id": str(project.id),
            "user_id": str(project.user_id),
            "name": project.name,
            "source_type": project.source_type,
            "source_url": project.source_url,
            "audio_path": project.audio_path,
            "status": project.status,
            "progress": project.progress,
            "created_at": project.created_at.isoformat(),
            "updated_at": project.updated_at.isoformat(),
        },
        "项目创建成功",
    )


@router.get("")
def list_projects_api(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    projects, total = list_projects(db, user=current_user, page=page, page_size=page_size)
    data = [
        {
            "id": str(project.id),
            "user_id": str(project.user_id),
            "name": project.name,
            "source_type": project.source_type,
            "source_url": project.source_url,
            "audio_path": project.audio_path,
            "status": project.status,
            "progress": project.progress,
            "created_at": project.created_at.isoformat(),
            "updated_at": project.updated_at.isoformat(),
        }
        for project in projects
    ]
    return paginated_response(data, page=page, page_size=page_size, total=total)


@router.get("/{project_id}")
def get_project_api(
    project_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    project = get_project_by_id(db, user=current_user, project_id=project_id)
    return success_response(
        {
            "id": str(project.id),
            "user_id": str(project.user_id),
            "name": project.name,
            "source_type": project.source_type,
            "source_url": project.source_url,
            "audio_path": project.audio_path,
            "status": project.status,
            "progress": project.progress,
            "created_at": project.created_at.isoformat(),
            "updated_at": project.updated_at.isoformat(),
        }
    )


@router.put("/{project_id}")
def update_project_api(
    project_id: str,
    payload: UpdateProjectRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    project = get_project_by_id(db, user=current_user, project_id=project_id)
    updated = update_project(
        db,
        project=project,
        name=payload.name,
        source_url=payload.source_url,
        audio_path=payload.audio_path,
        status=payload.status,
        progress=payload.progress,
    )
    return success_response(
        {
            "id": str(updated.id),
            "user_id": str(updated.user_id),
            "name": updated.name,
            "source_type": updated.source_type,
            "source_url": updated.source_url,
            "audio_path": updated.audio_path,
            "status": updated.status,
            "progress": updated.progress,
            "created_at": updated.created_at.isoformat(),
            "updated_at": updated.updated_at.isoformat(),
        },
        "项目更新成功",
    )


@router.delete("/{project_id}")
def delete_project_api(
    project_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    project = get_project_by_id(db, user=current_user, project_id=project_id)
    delete_project(db, project=project)
    return success_response({"deleted": True}, "项目删除成功")
