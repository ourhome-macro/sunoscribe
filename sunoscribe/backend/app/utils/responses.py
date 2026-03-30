from math import ceil
from typing import Any


def success_response(data: Any, message: str = "操作成功") -> dict:
    return {"success": True, "data": data, "message": message}


def paginated_response(data: list[Any], page: int, page_size: int, total: int) -> dict:
    total_pages = ceil(total / page_size) if page_size > 0 else 0
    return {
        "success": True,
        "data": data,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
        },
    }


def error_response(code: str, message: str, details: dict | None = None) -> dict:
    return {
        "success": False,
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
        },
    }
