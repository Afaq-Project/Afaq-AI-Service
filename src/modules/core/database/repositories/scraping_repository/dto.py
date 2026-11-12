# [OMA-W006-T006] DTO for Level 2 grant detail creation input

from typing import Any

from pydantic import BaseModel, ConfigDict

from prisma import Json


def to_json(val: Any) -> Any:
    """Wrap dict or list in Prisma Json representation."""
    if val is None:
        return None
    if isinstance(val, Json):
        return val
    return Json(val)


class GrantDetailCreateInput(BaseModel):
    """Input DTO for creating a comprehensive Level 2 RawGrantDetail record."""

    model_config = ConfigDict(extra="ignore")

    operation_id: str
    source_id: str
    source_url: str
    raw_payload: dict[str, Any]
    listing_id: str | None = None
    opportunity_group_id: str | None = None
    template_id: str | None = None
    template_version: int = 1
    image_url: str | None = None
    title_language: str = "und"
    body_language: str = "und"
    language_confidence: float = 0.0
    link_verification_status: str = "unverified"
    final_application_url: str | None = None
    is_legitimate_domain: bool | None = None
    has_attachment: bool = False
    attachment_s3_key: str | None = None
    attachment_metadata: dict[str, Any] | None = None
    status: str = "pending"
