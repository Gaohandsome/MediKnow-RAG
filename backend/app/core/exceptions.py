"""业务异常与统一错误响应。"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from loguru import logger
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException


class BizError(Exception):
    """可预期的业务异常。"""

    def __init__(self, message: str, status_code: int = 400, code: int = 400) -> None:
        self.message = message
        self.status_code = status_code
        self.code = code
        super().__init__(message)


def _payload(message: str, code: int) -> dict:
    return {"code": code, "message": message, "data": None}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(BizError)
    async def _biz_error(_: Request, exc: BizError) -> JSONResponse:
        logger.warning(f"业务异常：{exc.message}")
        return JSONResponse(status_code=exc.status_code, content=_payload(exc.message, exc.code))

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "请求异常"
        return JSONResponse(status_code=exc.status_code, content=_payload(message, exc.status_code))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(x) for x in first.get("loc", [])[1:]) or "参数"
        message = f"参数校验失败：{field} {first.get('msg', '')}".strip()
        return JSONResponse(status_code=422, content=_payload(message, 422))

    @app.exception_handler(SQLAlchemyError)
    async def _db_error(_: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.exception(f"数据库异常：{exc}")
        return JSONResponse(status_code=500, content=_payload("数据库操作失败，请稍后重试", 500))

    @app.exception_handler(Exception)
    async def _unknown_error(_: Request, exc: Exception) -> JSONResponse:
        logger.exception(f"未捕获异常：{exc}")
        return JSONResponse(status_code=500, content=_payload("服务器内部错误，请稍后重试", 500))
