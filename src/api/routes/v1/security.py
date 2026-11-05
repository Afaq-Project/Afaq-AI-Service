# [OMA-W001-T005] Security diagnostic REST endpoint

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from src.api.dependencies import require_api_key
from src.modules.core.auth.models import ApiKeyInfo
from src.modules.security.exceptions import SecurityValidationError
from src.modules.security.models import InspectUrlRequest, InspectUrlResponse
from src.modules.security.services.link_validator_service import LinkValidatorService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/security", tags=["security"])


# [OMA-W001-FIX-CYCLE-1] Inspect URL Diagnostic Route
@router.post(
    "/inspect-url",
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "URL verified as safe"},
        400: {"description": "Security validation failure or blocked destination"},
        401: {"description": "Invalid or missing API key"},
        422: {"description": "Unprocessable entity schema failure"},
    },
)
async def inspect_url(
    payload: InspectUrlRequest,
    key_info: Annotated[ApiKeyInfo, Depends(require_api_key)],
) -> InspectUrlResponse:
    """Diagnostic route for pre-request URL inspection, Anti-SSRF verification,

    and Chromium DNS pinning rule derivation.
    """
    logger.info(
        "Client %s requested inspection for URL: %s (base_url=%s, allow_redirects=%s)",
        key_info.name,
        payload.url,
        payload.base_url,
        payload.allow_redirects,
    )

    try:
        validated_url = await LinkValidatorService.validate_url(
            raw_url=payload.url,
            base_url=payload.base_url,
            allow_redirects=payload.allow_redirects,
        )
        return InspectUrlResponse(
            status="success",
            data=validated_url,
            message="URL verified as safe.",
        )
    except SecurityValidationError as exc:
        logger.warning(
            "Security validation failed for URL %s: [%s] %s",
            payload.url,
            exc.error_code,
            exc.message,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.message,
        ) from exc
