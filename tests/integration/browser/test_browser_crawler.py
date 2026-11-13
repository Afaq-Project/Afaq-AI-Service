# Integration tests for CrawlerService using local synthetic fixture server.
# Protects ARCH-003, ARCH-007, TEST-09, TEST-12, UC-02, and UC-07.
# Strictly zero external network access: all interactions bound to 127.0.0.1.

import asyncio
import urllib.parse
from collections.abc import Generator
from unittest.mock import patch

import pytest
from bs4 import BeautifulSoup
from playwright.async_api import Browser, BrowserContext, Page

from src.modules.scraping.exceptions import (
    ERR_ACCESS_CHALLENGE_BLOCKED,
    ERR_RATE_LIMITED_COOLDOWN,
    AccessChallengeBlockedError,
    RateLimitedCooldownError,
)
from src.modules.scraping.services.crawler_service import (
    MAX_SUBPAGES_CAP,
    CrawlerService,
    CrawlResult,
)
from src.modules.security.models import ValidatedUrl
from src.modules.security.services.link_validator_service import LinkValidatorService
from tests.integration.browser.fixture_server import LocalFixtureServer


@pytest.fixture(scope="module")
def fixture_server() -> Generator[LocalFixtureServer, None, None]:
    """Spins up a local synthetic HTTP fixture server on an ephemeral port."""
    server = LocalFixtureServer(host="127.0.0.1", port=0)
    server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture(autouse=True)
def allow_local_fixture_crawling(
    fixture_server: LocalFixtureServer,
) -> Generator[None, None, None]:
    """Allows CrawlerService to validate and navigate to the local fixture server.

    In production, LinkValidatorService enforces strict anti-SSRF by rejecting
    loopback addresses (127.0.0.1) and non-standard ports. This fixture configures
    LinkValidatorService to treat the local synthetic fixture server as legitimate
    for integration testing, satisfying the zero external crawling invariant.
    """
    server_port = fixture_server.port

    async def mock_validate_url(
        raw_url: str,
        allow_redirects: bool = True,
        **kwargs: object,
    ) -> ValidatedUrl:
        parsed = urllib.parse.urlsplit(raw_url)
        return ValidatedUrl(
            original_url=raw_url,
            canonical_url=raw_url,
            scheme=parsed.scheme or "http",
            host=parsed.hostname or "127.0.0.1",
            port=parsed.port or server_port,
            resolved_ip="127.0.0.1",
            is_https=False,
            redirect_hops=0,
            redirect_chain=[],
            dns_pinned_rule=f"--host-resolver-rules=MAP {parsed.hostname or '127.0.0.1'} 127.0.0.1",
        )

    orig_is_ip_blocked = LinkValidatorService.is_ip_blocked

    def mock_is_ip_blocked(ip: str) -> bool:
        if ip in ("127.0.0.1", "localhost", "::1"):
            return False
        return orig_is_ip_blocked(ip)

    with (
        patch.object(
            LinkValidatorService,
            "validate_url",
            side_effect=mock_validate_url,
        ),
        patch.object(
            LinkValidatorService,
            "is_ip_blocked",
            side_effect=mock_is_ip_blocked,
        ),
    ):
        yield


@pytest.mark.asyncio
async def test_js_rendered_listing_extraction(
    fixture_server: LocalFixtureServer,
) -> None:
    """Verifies headless Chromium renders dynamic JS-injected DOM before extraction."""
    crawler = CrawlerService()
    target_url = f"{fixture_server.base_url}/js-rendered"

    result = await crawler.crawl_page(
        url=target_url,
        wait_for_selector=".scholarship-card",
    )

    assert isinstance(result, CrawlResult)
    assert result.status_code == 200
    assert result.subpage_count == 1
    assert result.has_unhidden_tabs is False
    assert len(result.lineage_records) == 1
    assert result.lineage_records[0]["tree_depth"] == 0

    # Assert dynamic JavaScript-rendered content is present in the extracted DOM
    assert "Future Leaders Technology Scholarship" in result.html
    assert "Award Amount: $15,000" in result.html
    assert "Deadline: 2026-12-31" in result.html
    assert 'data-id="sch-2026-001"' in result.html


@pytest.mark.asyncio
async def test_unhiding_tabs_in_dom(fixture_server: LocalFixtureServer) -> None:
    """Verifies client-side JS and server-side DOM transformation unhide hidden tabs."""
    crawler = CrawlerService()
    target_url = f"{fixture_server.base_url}/hidden-tabs"

    result = await crawler.crawl_page(
        url=target_url,
        unhide_tabs=True,
    )

    assert result.status_code == 200
    assert result.has_unhidden_tabs is True

    # Parse resulting virtual DOM with BeautifulSoup
    soup = BeautifulSoup(result.html, "html.parser")

    # 1. Verify eligibility tab pane is transformed
    tab_eligibility = soup.find(id="tab-panel-eligibility")
    assert tab_eligibility is not None
    classes = tab_eligibility.get("class", [])
    assert "active" in classes
    assert "show" in classes
    assert "in" in classes
    assert not tab_eligibility.has_attr("hidden")
    assert tab_eligibility.get("aria-hidden") == "false"
    assert "display: block" in tab_eligibility.get("style", "")

    # 2. Verify benefits tab pane is unhidden
    tab_benefits = soup.find(id="tab-panel-benefits")
    assert tab_benefits is not None
    assert not tab_benefits.has_attr("hidden")
    assert "display: block" in tab_benefits.get("style", "")

    # 3. Verify collapsible accordion section is revealed
    accordion = soup.find(id="accordion-selection")
    assert accordion is not None
    assert "display: block" in accordion.get("style", "")
    assert "visibility: visible" in accordion.get("style", "")

    # 4. Verify hidden textual content is accessible in the final HTML
    assert "Hidden eligibility requirements and GPA thresholds." in result.html
    assert "Hidden monetary and housing allowance details." in result.html
    assert (
        "Hidden panel covering interview dates and evaluation matrices." in result.html
    )


@pytest.mark.asyncio
async def test_multi_page_traversal_depth_cap(
    fixture_server: LocalFixtureServer,
) -> None:
    """Verifies multi-page article recursion obeys user-configured max_subpages depth cap."""
    crawler = CrawlerService()
    target_url = f"{fixture_server.base_url}/pagination?page=1"

    # Limit to 3 pages even though 6 pages are available
    result = await crawler.crawl_page(
        url=target_url,
        has_multi_page=True,
        max_subpages=3,
    )

    assert result.status_code == 200
    assert result.subpage_count == 3
    assert len(result.lineage_records) == 3

    # Check lineage tree depth tracking
    assert result.lineage_records[0]["tree_depth"] == 0
    assert result.lineage_records[0]["page_index"] == 1
    assert result.lineage_records[1]["tree_depth"] == 1
    assert result.lineage_records[1]["page_index"] == 2
    assert result.lineage_records[2]["tree_depth"] == 2
    assert result.lineage_records[2]["page_index"] == 3

    # Check parent_id tracking in lineage
    assert result.lineage_records[0]["parent_id"] is None
    assert result.lineage_records[1]["parent_id"] == target_url

    # Check virtual DOM concatenation
    assert "Comprehensive Grant Guide - Part 1" in result.html
    assert "Comprehensive Grant Guide - Part 2" in result.html
    assert "Comprehensive Grant Guide - Part 3" in result.html
    assert "Comprehensive Grant Guide - Part 4" not in result.html

    # Check virtual DOM wrapper markup
    soup = BeautifulSoup(result.html, "html.parser")
    subpage_sections = soup.find_all("div", class_="afaq-subpage-section")
    assert len(subpage_sections) == 2  # Subpages 2 and 3 wrapped
    assert subpage_sections[0].get("data-page") == "2"
    assert subpage_sections[1].get("data-page") == "3"


@pytest.mark.asyncio
async def test_multi_page_default_hard_cap(
    fixture_server: LocalFixtureServer,
) -> None:
    """Verifies crawler respects MAX_SUBPAGES_CAP (5 pages) when more pages exist."""
    crawler = CrawlerService()
    target_url = f"{fixture_server.base_url}/pagination?page=1"

    result = await crawler.crawl_page(
        url=target_url,
        has_multi_page=True,
        max_subpages=MAX_SUBPAGES_CAP,
    )

    assert result.status_code == 200
    assert result.subpage_count == 5
    assert len(result.lineage_records) == 5

    assert "Comprehensive Grant Guide - Part 5" in result.html
    assert "Comprehensive Grant Guide - Part 6" not in result.html


@pytest.mark.asyncio
async def test_pagination_stagnant_page_cycle_cutoff(
    fixture_server: LocalFixtureServer,
) -> None:
    """Verifies crawler terminates recursion when next page link cycles back to visited page."""
    crawler = CrawlerService()
    target_url = f"{fixture_server.base_url}/stagnant-page"

    result = await crawler.crawl_page(
        url=target_url,
        has_multi_page=True,
        max_subpages=5,
    )

    assert result.status_code == 200
    assert result.subpage_count == 1
    assert len(result.lineage_records) == 1
    assert "Stagnant Listing Page" in result.html


@pytest.mark.asyncio
async def test_not_found_page_response(fixture_server: LocalFixtureServer) -> None:
    """Verifies crawler captures HTTP 404 status code and error page HTML body."""
    crawler = CrawlerService()
    target_url = f"{fixture_server.base_url}/not-found"

    result = await crawler.crawl_page(url=target_url)

    assert result.status_code == 404
    assert "404 Not Found" in result.html
    assert result.subpage_count == 1


@pytest.mark.asyncio
async def test_redirect_chain_navigation(
    fixture_server: LocalFixtureServer,
) -> None:
    """Verifies Chromium follows HTTP 302 redirects to final canonical target page."""
    crawler = CrawlerService()
    target_url = f"{fixture_server.base_url}/redirect-start"

    result = await crawler.crawl_page(url=target_url)

    assert result.status_code == 200
    assert "Redirect Target Reached" in result.html
    assert "canonical scholarship announcement page" in result.html


@pytest.mark.asyncio
async def test_access_challenge_blocked_error(
    fixture_server: LocalFixtureServer,
) -> None:
    """Verifies AccessChallengeBlockedError is raised when Cloudflare challenge tokens exist in DOM."""
    crawler = CrawlerService()
    target_url = f"{fixture_server.base_url}/bot-challenge"

    with pytest.raises(AccessChallengeBlockedError) as exc_info:
        await crawler.crawl_page(url=target_url)

    assert exc_info.value.code == ERR_ACCESS_CHALLENGE_BLOCKED
    assert exc_info.value.details["url"] == target_url


@pytest.mark.asyncio
async def test_rate_limited_cooldown_error(
    fixture_server: LocalFixtureServer,
) -> None:
    """Verifies RateLimitedCooldownError is raised when HTTP 429 has Retry-After > 300s."""
    crawler = CrawlerService()
    target_url = f"{fixture_server.base_url}/rate-limit?seconds=360"

    with pytest.raises(RateLimitedCooldownError) as exc_info:
        await crawler.crawl_page(url=target_url)

    assert exc_info.value.code == ERR_RATE_LIMITED_COOLDOWN
    assert exc_info.value.cool_down_seconds == 360.0
    assert exc_info.value.details["status_code"] == 429
    assert exc_info.value.details["retry_after"] == 360.0


@pytest.mark.asyncio
async def test_browser_context_cleanup_on_success(
    fixture_server: LocalFixtureServer,
) -> None:
    """Verifies browser, context, and page instances are explicitly closed after successful crawl."""
    crawler = CrawlerService()
    target_url = f"{fixture_server.base_url}/js-rendered"

    closed_resources: list[str] = []
    orig_browser_close = Browser.close
    orig_context_close = BrowserContext.close
    orig_page_close = Page.close

    async def tracked_browser_close(
        self: Browser, *args: object, **kwargs: object
    ) -> None:
        closed_resources.append("browser")
        await orig_browser_close(self, *args, **kwargs)

    async def tracked_context_close(
        self: BrowserContext, *args: object, **kwargs: object
    ) -> None:
        closed_resources.append("context")
        await orig_context_close(self, *args, **kwargs)

    async def tracked_page_close(self: Page, *args: object, **kwargs: object) -> None:
        closed_resources.append("page")
        await orig_page_close(self, *args, **kwargs)

    with (
        patch.object(Browser, "close", tracked_browser_close),
        patch.object(BrowserContext, "close", tracked_context_close),
        patch.object(Page, "close", tracked_page_close),
    ):
        result = await crawler.crawl_page(url=target_url)
        assert result.status_code == 200

    # Ensure page, context, and browser close were all invoked
    assert "page" in closed_resources
    assert "context" in closed_resources
    assert "browser" in closed_resources


@pytest.mark.asyncio
async def test_browser_context_cleanup_on_exception(
    fixture_server: LocalFixtureServer,
) -> None:
    """Verifies browser, context, and page instances are closed when crawl encounters an error."""
    crawler = CrawlerService()
    target_url = f"{fixture_server.base_url}/bot-challenge"

    closed_resources: list[str] = []
    orig_browser_close = Browser.close
    orig_context_close = BrowserContext.close
    orig_page_close = Page.close

    async def tracked_browser_close(
        self: Browser, *args: object, **kwargs: object
    ) -> None:
        closed_resources.append("browser")
        await orig_browser_close(self, *args, **kwargs)

    async def tracked_context_close(
        self: BrowserContext, *args: object, **kwargs: object
    ) -> None:
        closed_resources.append("context")
        await orig_context_close(self, *args, **kwargs)

    async def tracked_page_close(self: Page, *args: object, **kwargs: object) -> None:
        closed_resources.append("page")
        await orig_page_close(self, *args, **kwargs)

    with (
        patch.object(Browser, "close", tracked_browser_close),
        patch.object(BrowserContext, "close", tracked_context_close),
        patch.object(Page, "close", tracked_page_close),
    ):
        with pytest.raises(AccessChallengeBlockedError):
            await crawler.crawl_page(url=target_url)

    # All resources must be safely cleaned up despite the exception
    assert "page" in closed_resources
    assert "context" in closed_resources
    assert "browser" in closed_resources


@pytest.mark.asyncio
async def test_browser_context_cleanup_on_cancellation(
    fixture_server: LocalFixtureServer,
) -> None:
    """Verifies browser, context, and page instances are cleaned up when crawl task is cancelled."""
    crawler = CrawlerService()
    target_url = f"{fixture_server.base_url}/js-rendered"

    closed_resources: list[str] = []
    orig_browser_close = Browser.close
    orig_context_close = BrowserContext.close
    orig_page_close = Page.close
    orig_new_page = BrowserContext.new_page

    page_created_event = asyncio.Event()

    async def tracked_new_page(
        self: BrowserContext, *args: object, **kwargs: object
    ) -> Page:
        p = await orig_new_page(self, *args, **kwargs)
        page_created_event.set()
        return p

    async def tracked_browser_close(
        self: Browser, *args: object, **kwargs: object
    ) -> None:
        closed_resources.append("browser")
        await orig_browser_close(self, *args, **kwargs)

    async def tracked_context_close(
        self: BrowserContext, *args: object, **kwargs: object
    ) -> None:
        closed_resources.append("context")
        await orig_context_close(self, *args, **kwargs)

    async def tracked_page_close(self: Page, *args: object, **kwargs: object) -> None:
        closed_resources.append("page")
        await orig_page_close(self, *args, **kwargs)

    with (
        patch.object(BrowserContext, "new_page", tracked_new_page),
        patch.object(Browser, "close", tracked_browser_close),
        patch.object(BrowserContext, "close", tracked_context_close),
        patch.object(Page, "close", tracked_page_close),
    ):
        # We pass a non-existent selector with a timeout, and cancel mid-flight
        crawl_task = asyncio.create_task(
            crawler.crawl_page(
                url=target_url, wait_for_selector="#non-existent-selector"
            )
        )

        # Wait deterministically until page is instantiated before cancelling
        await page_created_event.wait()
        await asyncio.sleep(0.2)
        crawl_task.cancel()

        try:
            await crawl_task
        except asyncio.CancelledError:
            pass

    # Verify browser resource cleanup was triggered by finally block
    assert "page" in closed_resources
    assert "context" in closed_resources
    assert "browser" in closed_resources
