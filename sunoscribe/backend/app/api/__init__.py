from fastapi import APIRouter

from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.lyrics import router as lyrics_router
from app.api.projects import router as projects_router
from app.api.scores import router as scores_router
from app.api.tasks import router as tasks_router
from app.api.upload import router as upload_router
from app.api.users import router as users_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(projects_router)
api_router.include_router(upload_router)
api_router.include_router(scores_router)
api_router.include_router(lyrics_router)
api_router.include_router(tasks_router)
