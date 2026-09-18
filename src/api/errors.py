import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.modules.ai.constants import ERROR_MESSAGES
from src.modules.ai.exceptions import OpportunityNotFoundError
from src.modules.infrastructure.llm.exceptions import LLMError

logger = logging.getLogger(__name__)


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


def register_ai_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(LLMError, handle_llm_error)
    app.add_exception_handler(OpportunityNotFoundError, handle_opportunity_not_found)
