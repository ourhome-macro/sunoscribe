from fastapi import APIRouter, Query, Response, status

from app.services.pitch_runtime import build_pitch_runtime_health
from app.utils.responses import success_response

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
def health_api(
    response: Response,
    deep: bool = Query(False, description="Run heavier runtime checks, including RMVPE model construction."),
):
    data = {
        "status": "ok",
        "pitch": build_pitch_runtime_health(deep=deep),
    }
    if data["pitch"]["status"] == "fail":
        data["status"] = "fail"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif data["pitch"]["status"] == "degraded":
        data["status"] = "degraded"
    return success_response(data, "健康检查完成")


@router.get("/pitch")
def pitch_health_api(
    response: Response,
    deep: bool = Query(False, description="Run heavier runtime checks, including RMVPE model construction."),
):
    data = build_pitch_runtime_health(deep=deep)
    if data["status"] == "fail":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return success_response(data, "音高运行时健康检查完成")
