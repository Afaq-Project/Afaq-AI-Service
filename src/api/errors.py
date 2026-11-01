import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


def register_global_error_handlers(app: FastAPI) -> None:
    """تسجيل معالجات الأخطاء العامة للتطبيق."""
    pass
