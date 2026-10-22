"""通用响应封装。"""
from __future__ import annotations

from typing import Any


def ok(data: Any = None, message: str = "success") -> dict[str, Any]:
    """统一成功响应结构。"""
    return {"code": 0, "message": message, "data": data}


def page(items: list[Any], total: int, page_num: int = 1, page_size: int = 20) -> dict[str, Any]:
    """统一分页结构。"""
    return {"items": items, "total": total, "page": page_num, "page_size": page_size}
