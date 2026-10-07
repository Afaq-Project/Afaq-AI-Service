import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from prisma.errors import PrismaError

from src.modules.ai.constants import ERROR_MESSAGES
from src.modules.ai.exceptions import OpportunityNotFoundError
from src.modules.infrastructure.llm.exceptions import LLMError

logger = logging.getLogger(__name__)

DATABASE_ERROR_CODE = "database_unavailable"


def _error_response(status_code: int, code: str) -> JSONResponse:
    message = ERROR_MESSAGES.get(code, ERROR_MESSAGES["ai_error"])
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


async def handle_llm_error(request: Request, exc: Exception) -> JSONResponse:
    code = getattr(exc, "code", "ai_error")
    status_code = getattr(exc, "status_code", 500)
    logger.warning("AI request to %s failed (%s): %s", request.url.path, code, exc)
    return _error_response(status_code, code)


async def handle_opportunity_not_found(
    request: Request, exc: Exception
) -> JSONResponse:
    return _error_response(404, OpportunityNotFoundError.code)


async def handle_database_error(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Database call for %s failed: %s", request.url.path, exc)
    return _error_response(503, DATABASE_ERROR_CODE)


def register_ai_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(LLMError, handle_llm_error)
    app.add_exception_handler(OpportunityNotFoundError, handle_opportunity_not_found)
    app.add_exception_handler(PrismaError, handle_database_error)
