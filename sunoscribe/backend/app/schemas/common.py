from typing import Any

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class SuccessResponse(BaseModel):
    success: bool = True
    data: Any
    message: str = "操作成功"


class ErrorResponse(BaseModel):
    success: bool = False
    error: ErrorDetail


class Pagination(BaseModel):
    page: int
    page_size: int
    total: int
    total_pages: int


class PaginatedResponse(BaseModel):
    success: bool = True
    data: list[Any]
    pagination: Pagination
