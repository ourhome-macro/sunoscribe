from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api import api_router
from app.config import settings
from app.database import Base, engine
from app.utils.errors import AppError
from app.utils.responses import error_response

app = FastAPI(title=settings.app_name)


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError):
    status_code_map = {
        "VALIDATION_ERROR": 422,
        "AUTHENTICATION_ERROR": 401,
        "AUTHORIZATION_ERROR": 403,
        "NOT_FOUND": 404,
        "INTERNAL_ERROR": 500,
        "FILE_TOO_LARGE": 413,
        "UNSUPPORTED_FORMAT": 415,
    }
    return JSONResponse(
        status_code=status_code_map.get(exc.code, 500),
        content=error_response(exc.code, exc.message, exc.details),
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content=error_response("VALIDATION_ERROR", "请求参数校验失败", {"errors": exc.errors()}),
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(_: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content=error_response("INTERNAL_ERROR", "服务器内部错误", {"reason": str(exc)}),
    )


app.include_router(api_router, prefix=settings.api_prefix)
