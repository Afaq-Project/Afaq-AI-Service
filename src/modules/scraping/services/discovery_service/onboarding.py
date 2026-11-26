# [OMA-W006-T007] Onboarding coordinator for DiscoveryService

import logging
import urllib.parse
from typing import Any

import httpx
from bs4 import BeautifulSoup

from src.modules.core.config.settings import Settings, get_settings
from src.modules.core.database.repositories.scraping_repository import (
    ScrapingRepository,
)
from src.modules.infrastructure.llm.base import StructuredGenerator
from src.modules.infrastructure.llm.providers import create_structured_client
from src.modules.scraping.exceptions import (
    ERR_NOT_OPPORTUNITY_PORTAL,
    NotOpportunityPortalError,
)
from src.modules.scraping.models import SourceOnboardData, SourceOnboardResponse
from src.modules.scraping.services.crawler_service import CrawlerService
from src.modules.security.services.link_validator_service import LinkValidatorService
from src.modules.security.services.schema_validator_service import (
    SchemaValidatorService,
)

from .prompts import (
    DETAIL_TEMPLATE_SYSTEM_PROMPT,
    DISCOVERY_SYSTEM_PROMPT,
    escape_untrusted_content,
    package_untrusted_prompt,
)
from .relevance_gate import (
    DetailTemplateDiscoveryOutput,
    PlatformDiscoveryOutput,
    assert_opportunity_relevance,
)
from .skeletonizer import (
    HTML_PARSER,
    NOISE_TAGS,
    PRESERVED_ATTRIBUTES,
    collapse_repetitive_elements,
    skeletonize_dom,
)

logger = logging.getLogger(__name__)


class DiscoveryService:
    """Autonomous Stage 0 zero-configuration portal onboarding and DOM skeletonization service."""

    # Public aliases for backward compatibility
    NOISE_TAGS = NOISE_TAGS
    PRESERVED_ATTRIBUTES = PRESERVED_ATTRIBUTES

    def __init__(
        self,
        repository: ScrapingRepository | None = None,
        crawler: CrawlerService | None = None,
        llm_client: StructuredGenerator | None = None,
        settings: Settings | None = None,
    ) -> None:
        if repository is None:
            try:
                from src.modules.core.database.prisma_client import get_client

                db = get_client()
            except Exception:
                from prisma import Prisma

                db = Prisma()
            repository = ScrapingRepository(db=db)
        self._repository = repository
        self._crawler = crawler or CrawlerService(settings=settings)
        self._llm_client = llm_client
        self._settings = settings or get_settings()

    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def repository(self) -> ScrapingRepository:
        return self._repository

    @property
    def crawler(self) -> CrawlerService:
        return self._crawler

    @classmethod
    def _collapse_repetitive_elements(
        cls, soup: BeautifulSoup, max_keep: int = 2
    ) -> None:
        collapse_repetitive_elements(soup, max_keep=max_keep)

    @classmethod
    def skeletonize_dom(
        cls,
        html: str,
        target_min_bytes: int = 3000,
        target_max_bytes: int = 8000,
    ) -> str:
        return skeletonize_dom(
            html, target_min_bytes=target_min_bytes, target_max_bytes=target_max_bytes
        )

    @classmethod
    def escape_untrusted_content(cls, content: str) -> str:
        return escape_untrusted_content(content)

    @classmethod
    def package_untrusted_prompt(
        cls, skeleton_html: str, user_instruction: str = ""
    ) -> str:
        return package_untrusted_prompt(
            skeleton_html, user_instruction=user_instruction
        )

    # [OMA-W006-T005] Safe robots.txt retrieval with per-hop SSRF validation on redirects
    async def fetch_robots_txt(self, base_url: str) -> tuple[float, list[str]]:
        """Fetches and parses robots.txt with per-hop SSRF validation on redirects.

        The HTTP request is issued against the already validated destination IP
        (with a Host header preserving the original hostname) so DNS cannot be
        re-resolved to a private address between validation and the request.
        """
        delay = 1.0
        sitemaps: list[str] = []
        robots_url = urllib.parse.urljoin(base_url, "/robots.txt")

        try:
            val_robots = await LinkValidatorService.validate_url(
                robots_url, allow_redirects=False
            )
            current_url = val_robots.canonical_url
            current_host = val_robots.host
            current_ip = val_robots.resolved_ip
            current_scheme = val_robots.scheme
            current_port = val_robots.port
            max_hops = 5
            visited = {current_url}

            def _pinned_request_url(canonical: str, ip: str, port: int, scheme: str) -> str:
                parsed = urllib.parse.urlsplit(canonical)
                host_ip = ip
                if ":" in host_ip and not host_ip.startswith("["):
                    host_ip = f"[{host_ip}]"
                default_port = (port == 443 and scheme == "https") or (
                    port == 80 and scheme == "http"
                )
                netloc = host_ip if default_port else f"{host_ip}:{port}"
                return urllib.parse.urlunsplit(
                    (scheme, netloc, parsed.path or "/", parsed.query, parsed.fragment)
                )

            async with httpx.AsyncClient(timeout=5.0, follow_redirects=False) as client:
                resp = None
                for _ in range(max_hops + 1):
                    request_url = _pinned_request_url(
                        current_url, current_ip, current_port, current_scheme
                    )
                    resp = await client.get(
                        request_url,
                        headers={"Host": current_host},
                        extensions={"sni_hostname": current_host},
                    )
                    is_redirect = resp.status_code in (
                        301,
                        302,
                        303,
                        307,
                        308,
                    ) or (
                        300 <= resp.status_code < 400
                        and getattr(resp, "is_redirect", False)
                    )

                    if is_redirect:
                        location = resp.headers.get("location")
                        if not location:
                            break
                        next_url = urllib.parse.urljoin(current_url, location).strip()
                        if next_url in visited:
                            break
                        visited.add(next_url)
                        # Validate next_url per-hop against SSRF and IP blocklist
                        val_redirect = await LinkValidatorService.validate_url(
                            next_url, allow_redirects=False
                        )
                        current_url = val_redirect.canonical_url
                        current_host = val_redirect.host
                        current_ip = val_redirect.resolved_ip
                        current_scheme = val_redirect.scheme
                        current_port = val_redirect.port
                        continue
                    break

                if resp is not None and resp.status_code == 200:
                    for line in resp.text.splitlines():
                        line = line.strip()
                        if line.lower().startswith("crawl-delay:"):
                            parts = line.split(":", 1)
                            if len(parts) > 1:
                                try:
                                    d = float(parts[1].strip())
                                    if d > 0:
                                        delay = max(1.0, d)
                                except ValueError:
                                    pass
                        elif line.lower().startswith("sitemap:"):
                            parts = line.split(":", 1)
                            if len(parts) > 1:
                                smap = parts[1].strip()
                                if smap and smap not in sitemaps:
                                    sitemaps.append(smap)
        except Exception as exc:
            logger.debug("robots.txt not available for %s: %s", base_url, exc)

        return delay, sitemaps

    async def _fetch_homepage_dom(self, canonical_url: str) -> str:
        try:
            crawl_result = await self._crawler.crawl_page(
                canonical_url,
                unhide_tabs=False,
                has_multi_page=False,
            )
        except Exception as exc:
            logger.warning(
                "Failed to fetch homepage DOM for %s: %s", canonical_url, exc
            )
            raise NotOpportunityPortalError(
                message=f"Target website unreachable or failed to load: {exc}",
                code=ERR_NOT_OPPORTUNITY_PORTAL,
                details={"url": canonical_url, "error": str(exc)},
            ) from exc

        if (
            crawl_result.status_code >= 400
            or not crawl_result.html
            or not crawl_result.html.strip()
        ):
            raise NotOpportunityPortalError(
                message=f"Target website unreachable or returned HTTP {crawl_result.status_code}",
                code=ERR_NOT_OPPORTUNITY_PORTAL,
                details={
                    "url": canonical_url,
                    "status_code": crawl_result.status_code,
                },
            )
        return crawl_result.html

    # [OMA-W008-T005] Reliable source deactivation and error logging before raising NotOpportunityPortalError
    async def _handle_irrelevant_source(
        self, canonical_url: str, discovery: PlatformDiscoveryOutput, domain: str
    ) -> None:
        existing_source = await self._repository.get_source_by_url(canonical_url)
        if existing_source:
            try:
                await self._repository.deactivate_source(existing_source.id)
            except Exception as exc:
                logger.error(
                    "Database error while deactivating irrelevant source %s: %s",
                    existing_source.id,
                    exc,
                )
        assert_opportunity_relevance(discovery, canonical_url, domain)

    async def _synthesize_detail_template(
        self,
        llm_client: StructuredGenerator,
        discovery: PlatformDiscoveryOutput,
        homepage_html: str,
        skeleton_dom: str,
        canonical_url: str,
    ) -> tuple[
        DetailTemplateDiscoveryOutput | None, bool, str | None, bool, str | None
    ]:
        has_multi_tab = False
        tab_container_selector: str | None = None
        has_multi_page = False
        subpage_pagination_selector: str | None = None
        detail_discovery: DetailTemplateDiscoveryOutput | None = None

        detail_url_candidate = discovery.representative_detail_url
        if (
            discovery.page_role == "catalog"
            and not detail_url_candidate
            and discovery.card_container_selector
        ):
            try:
                soup_entry = BeautifulSoup(homepage_html, HTML_PARSER)
                card_el = soup_entry.select_one(discovery.card_container_selector)
                if card_el:
                    a_tag = card_el.find("a", href=True)
                    if a_tag and a_tag.get("href"):
                        detail_url_candidate = a_tag["href"]
            except Exception:
                pass

        if discovery.page_role == "catalog" and detail_url_candidate:
            representative_url = urllib.parse.urljoin(
                canonical_url, detail_url_candidate.strip()
            )
            try:
                val_detail = await LinkValidatorService.validate_url(
                    representative_url, allow_redirects=True
                )
                detail_crawl = await self._crawler.crawl_page(
                    val_detail.canonical_url, unhide_tabs=True, has_multi_page=False
                )
                if detail_crawl.status_code < 400 and detail_crawl.html:
                    detail_skeleton = self.skeletonize_dom(detail_crawl.html)
                    detail_prompt = self.package_untrusted_prompt(
                        detail_skeleton,
                        user_instruction=(
                            f"Opportunity detail URL: {val_detail.canonical_url}\n"
                            "Analyze the detail page skeleton and extract extraction selectors."
                        ),
                    )
                    detail_completion = await llm_client.generate(
                        system=DETAIL_TEMPLATE_SYSTEM_PROMPT,
                        prompt=detail_prompt,
                        output_type=DetailTemplateDiscoveryOutput,
                    )
                    detail_discovery = detail_completion.output
                    has_multi_tab = (
                        detail_discovery.has_multi_tab or detail_crawl.has_unhidden_tabs
                    )
                    tab_container_selector = detail_discovery.tab_container_selector
                    has_multi_page = detail_discovery.has_multi_page
                    subpage_pagination_selector = (
                        detail_discovery.subpage_pagination_selector
                    )
            except Exception as exc:
                logger.warning(
                    "2nd-hop detail crawl failed for %s: %s", representative_url, exc
                )
        elif discovery.page_role == "detail":
            try:
                detail_prompt = self.package_untrusted_prompt(
                    skeleton_dom,
                    user_instruction=(
                        f"Opportunity detail URL: {canonical_url}\n"
                        "Analyze the detail page skeleton and extract extraction selectors."
                    ),
                )
                detail_completion = await llm_client.generate(
                    system=DETAIL_TEMPLATE_SYSTEM_PROMPT,
                    prompt=detail_prompt,
                    output_type=DetailTemplateDiscoveryOutput,
                )
                detail_discovery = detail_completion.output
                has_multi_tab = detail_discovery.has_multi_tab
                tab_container_selector = detail_discovery.tab_container_selector
                has_multi_page = detail_discovery.has_multi_page
                subpage_pagination_selector = (
                    detail_discovery.subpage_pagination_selector
                )
            except Exception as exc:
                logger.warning("Detail template synthesis failed: %s", exc)

        return (
            detail_discovery,
            has_multi_tab,
            tab_container_selector,
            has_multi_page,
            subpage_pagination_selector,
        )

    async def _persist_source_and_configs(
        self,
        canonical_url: str,
        name: str | None,
        created_by: str | None,
        discovery: PlatformDiscoveryOutput,
        domain: str,
        rate_limit_delay_sec: float,
        robots_sitemaps: list[str],
        has_multi_tab: bool,
        tab_container_selector: str | None,
        has_multi_page: bool,
        subpage_pagination_selector: str | None,
    ) -> tuple[Any, Any]:
        site_name = name or discovery.site_name or domain
        effective_domain = discovery.domain or domain
        languages = (
            discovery.supported_languages
            if discovery.supported_languages
            else ["ar", "en"]
        )

        source = await self._repository.get_source_by_url(canonical_url)
        if source is None:
            source = await self._repository.create_source(
                url=canonical_url,
                name=site_name,
                created_by=created_by,
                is_active=True,
            )
        else:
            await self._repository._db.source.update(
                where={"id": source.id},
                data={"name": site_name, "is_active": True},
            )

        config_data = {
            "domain": effective_domain,
            "site_name": site_name,
            "site_description": discovery.site_description,
            "supported_languages": languages,
            "pagination_type": discovery.pagination_type or "next_button",
            "pagination_config": {
                **(discovery.pagination_config or {}),
                "catalog_navigation": discovery.catalog_navigation or {},
            },
            "ordering_strategy": discovery.ordering_strategy
            or "chronological_descending",
            "rate_limit_delay_sec": rate_limit_delay_sec,
            "robots_txt_sitemaps": robots_sitemaps,
            "has_multi_tab_details": has_multi_tab,
            "tab_container_selector": tab_container_selector,
            "has_multi_page_details": has_multi_page,
            "subpage_pagination_selector": subpage_pagination_selector,
            "is_locked": False,
        }
        source_config = await self._repository.upsert_source_config(
            source_id=source.id, config_data=config_data
        )
        return source, source_config

    async def _persist_templates(
        self,
        source_id: str,
        effective_domain: str,
        discovery: PlatformDiscoveryOutput,
        detail_discovery: DetailTemplateDiscoveryOutput | None,
    ) -> None:
        if (
            discovery.page_role == "catalog"
            and discovery.card_container_selector
            and discovery.card_title_selector
        ):
            l1_schema = {
                "schema_name": f"{effective_domain}_catalog_l1",
                "selectors": {
                    "card_container": discovery.card_container_selector,
                    "card_title": discovery.card_title_selector,
                    "card_link": discovery.card_link_selector
                    or discovery.card_title_selector,
                },
            }
            try:
                val_result = await SchemaValidatorService.validate_template_schema(
                    l1_schema, raise_on_error=False
                )
                if val_result.is_valid:
                    await self._repository.create_template(
                        source_id=source_id,
                        level=1,
                        layout_signature=f"{effective_domain}_catalog_v1",
                        template_schema=l1_schema,
                        schema_type="CSS",
                    )
            except Exception as exc:
                logger.warning("Failed to validate or create Level 1 template: %s", exc)

        if detail_discovery and detail_discovery.title_selector:
            l2_schema = {
                "schema_name": f"{effective_domain}_detail_l2",
                "selectors": {
                    "title": detail_discovery.title_selector,
                    "content": detail_discovery.content_selector or "article",
                },
            }
            if detail_discovery.deadline_selector:
                l2_schema["selectors"]["deadline"] = detail_discovery.deadline_selector
            if detail_discovery.application_link_selector:
                l2_schema["selectors"][
                    "application_link"
                ] = detail_discovery.application_link_selector

            try:
                val_l2 = await SchemaValidatorService.validate_template_schema(
                    l2_schema, raise_on_error=False
                )
                if val_l2.is_valid:
                    await self._repository.create_template(
                        source_id=source_id,
                        level=2,
                        layout_signature=f"{effective_domain}_detail_v1",
                        template_schema=l2_schema,
                        schema_type="CSS",
                    )
            except Exception as exc:
                logger.warning("Failed to validate or create Level 2 template: %s", exc)

    async def onboard_source(
        self,
        url: str,
        name: str | None = None,
        created_by: str | None = None,
    ) -> SourceOnboardResponse:
        """Executes Stage 0 autonomous discovery and technical configuration for a target portal."""
        # 1. Pre-flight URL & security validation
        validated_url = await LinkValidatorService.validate_url(
            url, allow_redirects=True
        )
        canonical_url = validated_url.canonical_url
        domain = validated_url.host

        # 2. Pre-flight robots.txt parsing
        rate_limit_delay_sec, robots_sitemaps = await self.fetch_robots_txt(
            canonical_url
        )

        # 3. Capture homepage DOM in headless Chromium with DNS pinning
        homepage_html = await self._fetch_homepage_dom(canonical_url)

        # 4. DOM skeletonization down to 3-8 KB
        skeleton_dom = self.skeletonize_dom(homepage_html)

        # 5. XML prompt packaging in <untrusted_web_content> sandbox
        user_prompt = self.package_untrusted_prompt(
            skeleton_dom,
            user_instruction=(
                f"Target URL: {canonical_url}\n"
                "Analyze the skeletonized DOM to determine opportunity relevance, "
                "platform metadata, and catalog structure."
            ),
        )

        # 6. AI platform mapping via structured LLM client
        llm_client = self._llm_client or create_structured_client(self._settings)
        completion = await llm_client.generate(
            system=DISCOVERY_SYSTEM_PROMPT,
            prompt=user_prompt,
            output_type=PlatformDiscoveryOutput,
        )
        discovery = completion.output

        # 7. Relevance Gate
        if not discovery.is_opportunity_portal:
            await self._handle_irrelevant_source(canonical_url, discovery, domain)

        # 8. Template synthesis is deferred to runtime phases. Onboarding only
        #    records catalog navigation; it never analyzes a generic homepage as
        #    a detail page and never creates Level 1/Level 2 scraper templates.
        detail_discovery = None
        has_multi_tab = False
        tab_container_selector = None
        has_multi_page = False
        subpage_pagination_selector = None

        # 9. Persist Source & SourceConfig
        source, source_config = await self._persist_source_and_configs(
            canonical_url,
            name,
            created_by,
            discovery,
            domain,
            rate_limit_delay_sec,
            robots_sitemaps,
            has_multi_tab,
            tab_container_selector,
            has_multi_page,
            subpage_pagination_selector,
        )

        # 10. Template creation is deferred to first real catalog/detail page via TemplateEngine.
        # Onboarding only persists catalog navigation (no homepage template).
        effective_domain = discovery.domain or domain

        # 11. Return SourceOnboardResponse
        languages = (
            discovery.supported_languages
            if discovery.supported_languages
            else ["ar", "en"]
        )
        return SourceOnboardResponse(
            status="success",
            data=SourceOnboardData(
                source_id=source.id,
                domain=effective_domain,
                site_name=source.name or effective_domain,
                supported_languages=languages,
                pagination_type=source_config.pagination_type,
                pagination_config=(
                    source_config.pagination_config
                    if isinstance(source_config.pagination_config, dict)
                    else {}
                ),
                ordering_strategy=source_config.ordering_strategy,
                rate_limit_delay_sec=source_config.rate_limit_delay_sec,
                is_active=True,
            ),
            message="Source onboarded and technical configuration populated successfully.",
        )
