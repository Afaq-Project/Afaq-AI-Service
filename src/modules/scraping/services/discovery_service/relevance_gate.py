# [OMA-W006-T007] Relevance gate models and checks for discovery service

import logging
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from src.modules.scraping.exceptions import (
    ERR_NOT_OPPORTUNITY_PORTAL,
    NotOpportunityPortalError,
)

logger = logging.getLogger(__name__)


class PlatformDiscoveryOutput(BaseModel):
    """Structured AI output for Stage 0 platform mapping and relevance validation."""

    model_config = ConfigDict(extra="ignore")

    is_opportunity_portal: bool = Field(
        description="True if website provides educational opportunities, scholarships, fellowships, or grants. False if commercial blog, e-commerce, spam, or irrelevant."
    )
    site_name: str = Field(
        description="Official name of the scholarship/opportunity platform or organization"
    )
    domain: str = Field(description="Domain name of the website")
    site_description: str | None = Field(
        default=None,
        description="Short summary of the portal's purpose and opportunities offered",
    )
    supported_languages: list[str] = Field(
        default_factory=lambda: ["ar", "en"],
        description="List of ISO 639-1 language codes observed or supported, e.g. ['ar', 'en']",
    )
    is_catalog_page: bool | None = Field(
        default=None,
        description="True if the current page is a catalog or listing of opportunities; False if it is a single detail page or generic home",
    )
    page_role: str = Field(
        ...,
        validation_alias=AliasChoices(
            "page_role",
            "entry_page_type",
            "page_type",
            "entry_type",
            "role",
        ),
        description=(
            "Explicit, non-defaulted page role for Level 0 discovery: "
            "'homepage' (generic landing/home page), 'catalog' (the entry URL is "
            "itself an opportunity listing/catalog), or 'detail' (a single "
            "opportunity detail page). A direct catalog URL must be 'catalog', "
            "not 'homepage'."
        ),
    )
    representative_detail_url: str | None = Field(
        default=None,
        description="If this is a catalog page, absolute or relative URL of one representative opportunity detail link from the cards",
    )
    pagination_type: str = Field(
        default="next_button",
        description="Pagination mechanism: 'url_param', 'next_button', 'infinite_scroll', or 'none'",
    )
    pagination_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Configuration for pagination, e.g. {'param': 'page', 'step': 1} or {'next_selector': 'a.next'}",
    )
    ordering_strategy: str = Field(
        default="chronological_descending",
        description="Ordering strategy: 'chronological_descending', 'deadline_ascending', 'featured_sponsored_mixed', or 'unknown'",
    )
    card_container_selector: str | None = Field(
        default=None,
        description="CSS selector for opportunity card items on catalog (e.g. '.post-card', 'article.entry')",
    )
    card_title_selector: str | None = Field(
        default=None,
        description="CSS selector relative to card container for opportunity title",
    )
    card_link_selector: str | None = Field(
        default=None,
        description="CSS selector relative to card container for opportunity detail URL",
    )
    catalog_navigation: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "How to reach the opportunity catalog from the entry page: "
            "{'type': 'url'|'tab', 'href': str|None, 'selector': str|None}. "
            "Analyzed once during onboarding; no homepage template is created."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _derive_page_role(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        role = None
        for key in ("page_role", "entry_page_type", "page_type", "entry_type", "role"):
            value = data.get(key)
            if value is not None:
                role = value
                break
        if role is None:
            is_catalog = data.get("is_catalog_page")
            if is_catalog is True:
                role = "catalog"
            else:
                # is_catalog_page=False cannot distinguish a homepage from a
                # detail page; require an explicit page_role instead of guessing.
                raise ValueError("page_role is required for Level 0 discovery")
        if role is None:
            raise ValueError("page_role is required for Level 0 discovery")
        data = dict(data)
        data["page_role"] = role
        return data

    @model_validator(mode="after")
    def _normalize_page_role(self) -> "PlatformDiscoveryOutput":
        role = str(self.page_role).strip().lower()
        aliases = {
            "home": "homepage",
            "home_page": "homepage",
            "landing": "homepage",
            "generic_home": "homepage",
            "direct_catalog": "catalog",
            "listing": "catalog",
            "catalog_page": "catalog",
            "list": "catalog",
            "detail_page": "detail",
            "opportunity_detail": "detail",
            "single_detail": "detail",
        }
        role = aliases.get(role, role)
        if role not in {"homepage", "catalog", "detail"}:
            raise ValueError(
                f"page_role must be one of homepage, catalog, detail; got {role!r}"
            )
        self.page_role = role
        self.is_catalog_page = role == "catalog"
        return self


class DetailTemplateDiscoveryOutput(BaseModel):
    """Structured AI output for Level 2 detail template synthesis."""

    model_config = ConfigDict(extra="ignore")

    title_selector: str = Field(
        default="h1", description="CSS selector for opportunity title"
    )
    content_selector: str = Field(
        default="article",
        description="CSS selector for main description/content body container",
    )
    deadline_selector: str | None = Field(
        default=None, description="CSS selector for application deadline field"
    )
    application_link_selector: str | None = Field(
        default=None,
        description="CSS selector for external apply now button or link",
    )
    has_multi_tab: bool = Field(
        default=False,
        description="True if detail page contains tabbed containers (.tab-pane, [role='tabpanel'])",
    )
    tab_container_selector: str | None = Field(
        default=None,
        description="CSS selector for tab containers if multi-tab is detected",
    )
    has_multi_page: bool = Field(
        default=False,
        description="True if detail article spans multiple paginated sub-pages",
    )
    subpage_pagination_selector: str | None = Field(
        default=None,
        description="CSS selector for next sub-page links if multi-page is detected",
    )


def assert_opportunity_relevance(
    discovery: PlatformDiscoveryOutput,
    canonical_url: str,
    domain: str,
) -> None:
    """Verifies that the discovered site is an educational opportunity portal, raising if not."""
    if not discovery.is_opportunity_portal:
        raise NotOpportunityPortalError(
            message="Target website does not contain educational opportunities",
            code=ERR_NOT_OPPORTUNITY_PORTAL,
            details={
                "url": canonical_url,
                "domain": discovery.domain or domain,
            },
        )
