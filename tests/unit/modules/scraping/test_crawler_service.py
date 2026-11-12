# [OMA-W005-T009] [OMA-W005-T010] [OMA-W005-T014] Unit tests for CrawlerService

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.modules.scraping.exceptions import (
    ERR_ACCESS_CHALLENGE_BLOCKED,
    ERR_RATE_LIMITED_COOLDOWN,
    AccessChallengeBlockedError,
    RateLimitedCooldownError,
)
from src.modules.scraping.services.crawler_service import (
    JS_UNHIDE_TABS_SCRIPT,
    CrawlerService,
    CrawlResult,
)
from src.modules.security.models import ValidatedUrl


# [OMA-W005-T009] Test Chromium memory pruning flags strictly bound to <= 1 GB RAM server limit
def test_build_launch_args_memory_flags():
    """Protects ARCH-003 & UC-02: Verifies required memory pruning flags are passed to Chromium."""
    args = CrawlerService.build_launch_args()

    assert "--disable-dev-shm-usage" in args
    assert "--no-zygote" in args
    assert "--disable-gpu" in args
    assert "--no-sandbox" in args
    assert "--single-process" in args
    assert "--disable-extensions" in args
    assert "--disable-background-networking" in args


# [OMA-W005-T009] Test DNS pinning flag construction in Chromium launch args
def test_build_launch_args_dns_pinning():
    """Protects ARCH-007 & TEST-09: Verifies DNS pinning rule is passed via --host-resolver-rules."""
    args = CrawlerService.build_launch_args(
        pinned_host="scholarships.example.edu",
        pinned_ip="93.184.216.34",
    )
    expected_rule = "--host-resolver-rules=MAP scholarships.example.edu 93.184.216.34"
    assert expected_rule in args


# [OMA-W005-T009] Test route handler sub-request interception and Anti-SSRF blocking
@pytest.mark.asyncio
async def test_route_interception_ssrf_and_trackers():
    """Protects ARCH-007 & TEST-09: Intercepts sub-requests to block private IPs, trackers, and heavy media."""
    # 1. Block private IP SSRF attempt
    route_ssrf = MagicMock()
    route_ssrf.abort = AsyncMock()
    route_ssrf.continue_ = AsyncMock()
    req_ssrf = MagicMock()
    req_ssrf.url = "http://127.0.0.1:8080/internal/secret"
    req_ssrf.resource_type = "fetch"
    route_ssrf.request = req_ssrf

    await CrawlerService._handle_route_interception(route_ssrf)
    route_ssrf.abort.assert_awaited_once_with("blockedbyclient")
    route_ssrf.continue_.assert_not_awaited()

    # 2. Block tracking network sub-request
    route_tracker = MagicMock()
    route_tracker.abort = AsyncMock()
    route_tracker.continue_ = AsyncMock()
    req_tracker = MagicMock()
    req_tracker.url = "https://www.google-analytics.com/analytics.js"
    req_tracker.resource_type = "script"
    route_tracker.request = req_tracker

    await CrawlerService._handle_route_interception(route_tracker)
    route_tracker.abort.assert_awaited_once_with("blockedbyclient")
    route_tracker.continue_.assert_not_awaited()

    # 3. Block heavy media when block_media=True
    route_media = MagicMock()
    route_media.abort = AsyncMock()
    route_media.continue_ = AsyncMock()
    req_media = MagicMock()
    req_media.url = "https://scholarships.example.edu/banner.png"
    req_media.resource_type = "image"
    route_media.request = req_media

    await CrawlerService._handle_route_interception(route_media, block_media=True)
    route_media.abort.assert_awaited_once_with("blockedbyclient")
    route_media.continue_.assert_not_awaited()

    # 4. Allow legitimate public sub-request
    route_ok = MagicMock()
    route_ok.abort = AsyncMock()
    route_ok.continue_ = AsyncMock()
    req_ok = MagicMock()
    req_ok.url = "http://93.184.216.34/api/grants.json"
    req_ok.resource_type = "fetch"
    route_ok.request = req_ok

    await CrawlerService._handle_route_interception(route_ok, block_media=False)
    route_ok.abort.assert_not_awaited()
    route_ok.continue_.assert_awaited_once()


# [OMA-W005-T010] Test client-side JavaScript multi-tab unhiding on HTML markup
def test_unhide_tabs_in_html():
    """Protects UC-08 & TEST-08: Verifies static DOM-level unhiding for .tab-pane and [role='tabpanel']."""
    html_input = """
    <div class="tabs-container">
        <div class="tab-pane fade" id="overview" style="display: none;">Overview Content</div>
        <div role="tabpanel" class="hidden" hidden aria-hidden="true" style="visibility: hidden;">Eligibility Content</div>
        <div class="accordion-collapse collapse">Benefits Content</div>
    </div>
    """

    unhidden_html = CrawlerService.unhide_tabs_in_html(html_input)

    # .tab-pane has active, show, in added and fade removed; display: none replaced with display: block
    assert "active" in unhidden_html
    assert "show" in unhidden_html
    assert "in" in unhidden_html
    assert "display: block;" in unhidden_html

    # [role="tabpanel"] has hidden attribute removed and aria-hidden="false"
    assert 'aria-hidden="false"' in unhidden_html
    assert "visibility: visible;" in unhidden_html
    assert 'hidden=""' not in unhidden_html


# [OMA-W005-T010] Test client-side multi-tab script execution in Playwright Page
@pytest.mark.asyncio
async def test_unhide_tabs_in_page():
    """Protects UC-08 & TEST-08: Verifies page.evaluate is invoked with JS_UNHIDE_TABS_SCRIPT."""
    mock_page = MagicMock()
    mock_page.evaluate = AsyncMock()

    await CrawlerService.unhide_tabs_in_page(mock_page)

    mock_page.evaluate.assert_awaited_once_with(JS_UNHIDE_TABS_SCRIPT)


# [OMA-W005-T010] Test multi-page article sub-page link extraction
def test_extract_subpage_link():
    """Protects UC-09 & TEST-09: Verifies next subpage link extraction across CSS classes and multilingual labels."""
    base_url = "https://scholarships.example.edu/article/1"

    # Explicit selector
    html_custom = (
        '<div class="custom-pager"><a href="/article/1/p2">Next Part</a></div>'
    )
    link = CrawlerService.extract_subpage_link(
        html_custom, base_url, subpage_selector=".custom-pager a"
    )
    assert link == "https://scholarships.example.edu/article/1/p2"

    # Standard selector a.next
    html_standard = (
        '<div class="page-links"><a class="next" href="page2.html">2</a></div>'
    )
    link_std = CrawlerService.extract_subpage_link(html_standard, base_url)
    assert link_std == "https://scholarships.example.edu/article/page2.html"

    # Arabic label link "الصفحة التالية"
    html_arabic = '<div class="pager"><a href="/grant/part-2">الصفحة التالية</a></div>'
    link_ar = CrawlerService.extract_subpage_link(
        html_arabic, "https://scholarships.example.edu/grant"
    )
    assert link_ar == "https://scholarships.example.edu/grant/part-2"

    # No subpage link present
    html_none = "<article><p>Single page announcement</p></article>"
    assert CrawlerService.extract_subpage_link(html_none, base_url) is None


# [OMA-W005-T010] Test multi-page virtual DOM concatenation
def test_concatenate_virtual_dom():
    """Protects UC-09 & TEST-09: Concatenates sub-pages into unified DOM with lineage tracking wrappers."""
    page_1 = """
    <html><body>
        <article class="entry-content">
            <h1>Scholarship Overview</h1>
            <p>Page 1 paragraph</p>
        </article>
    </body></html>
    """
    page_2 = """
    <html><body>
        <article class="entry-content">
            <h2>Eligibility Criteria</h2>
            <p>Page 2 paragraph</p>
        </article>
    </body></html>
    """

    virtual_dom = CrawlerService.concatenate_virtual_dom([page_1, page_2])

    assert "Scholarship Overview" in virtual_dom
    assert "Eligibility Criteria" in virtual_dom
    assert 'class="afaq-subpage-section"' in virtual_dom
    assert 'data-page="2"' in virtual_dom
    assert 'data-tree-depth="1"' in virtual_dom


# [OMA-W005-T014] Test Cloudflare and anti-bot challenge DOM detection
def test_detect_access_challenge():
    """Protects UC-12 & TEST-12: Verifies detection of Turnstile, CAPTCHA, and Cloudflare challenge tokens."""
    challenge_html_turnstile = (
        '<html><body><div id="cf-turnstile">Checking browser</div></body></html>'
    )
    challenge_html_title = "<html><head><title>Just a Moment...</title></head></html>"
    clean_html = "<html><body><h1>King Fahd University Scholarship</h1></body></html>"

    assert CrawlerService.detect_access_challenge(challenge_html_turnstile) is True
    assert CrawlerService.detect_access_challenge(challenge_html_title) is True
    assert CrawlerService.detect_access_challenge(clean_html) is False
    assert CrawlerService.detect_access_challenge("") is False


# [OMA-W005-T014] Test HTTP 429/503 rate-limiting cooldown check
def test_check_rate_limit():
    """Protects UC-13 & TEST-13: Verifies HTTP 429 with Retry-After > 300s raises RateLimitedCooldownError."""
    # HTTP 429 with Retry-After: 600s -> raises RateLimitedCooldownError
    with pytest.raises(RateLimitedCooldownError) as exc_info:
        CrawlerService.check_rate_limit(429, {"Retry-After": "600"})
    assert exc_info.value.code == ERR_RATE_LIMITED_COOLDOWN
    assert exc_info.value.cool_down_seconds == 600.0

    # HTTP 429 with Retry-After: 60s (<= 300s) -> does not trigger long cooldown exception
    CrawlerService.check_rate_limit(429, {"Retry-After": "60"})

    # HTTP 200 -> does not raise
    CrawlerService.check_rate_limit(200, {})


# [OMA-W005-T014] Test crawl_page full lifecycle with mocked Playwright and LinkValidatorService
@pytest.mark.asyncio
async def test_crawl_page_happy_path():
    """Protects UC-01 & TEST-01: Verifies crawl_page runs Playwright browser within concurrency lock."""
    service = CrawlerService()

    validated_dummy = ValidatedUrl(
        original_url="https://scholarships.example.edu/list",
        canonical_url="https://scholarships.example.edu/list",
        scheme="https",
        host="scholarships.example.edu",
        port=443,
        resolved_ip="93.184.216.34",
        is_https=True,
        dns_pinned_rule="--host-resolver-rules=MAP scholarships.example.edu 93.184.216.34",
    )

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.headers = {"content-type": "text/html"}

    mock_page = MagicMock()
    mock_page.goto = AsyncMock(return_value=mock_resp)
    mock_page.content = AsyncMock(
        return_value="<html><body><h1>Scholarships Catalog</h1></body></html>"
    )
    mock_page.route = AsyncMock()
    mock_page.close = AsyncMock()

    mock_context = MagicMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_context.close = AsyncMock()

    mock_browser = MagicMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.close = AsyncMock()

    mock_playwright_cm = MagicMock()
    mock_playwright_cm.chromium.launch = AsyncMock(return_value=mock_browser)

    with (
        patch(
            "src.modules.security.services.link_validator_service.LinkValidatorService.validate_url",
            new_callable=AsyncMock,
            return_value=validated_dummy,
        ),
        patch(
            "src.modules.scraping.services.crawler_service.async_playwright"
        ) as mock_ap,
    ):
        mock_ap.return_value.__aenter__.return_value = mock_playwright_cm

        res = await service.crawl_page("https://scholarships.example.edu/list")

        assert isinstance(res, CrawlResult)
        assert res.status_code == 200
        assert "Scholarships Catalog" in res.html
        assert res.resolved_ip == "93.184.216.34"
        assert res.subpage_count == 1
        assert len(res.lineage_records) == 1


# [OMA-W005-T014] Test crawl_page raising AccessChallengeBlockedError when bot challenge detected
@pytest.mark.asyncio
async def test_crawl_page_raises_on_bot_challenge():
    """Protects UC-12 & TEST-12: Verifies AccessChallengeBlockedError raised when challenge DOM encountered."""
    service = CrawlerService()

    validated_dummy = ValidatedUrl(
        original_url="https://scholarships.example.edu/blocked",
        canonical_url="https://scholarships.example.edu/blocked",
        scheme="https",
        host="scholarships.example.edu",
        port=443,
        resolved_ip="93.184.216.34",
        is_https=True,
        dns_pinned_rule="--host-resolver-rules=MAP scholarships.example.edu 93.184.216.34",
    )

    mock_resp = MagicMock()
    mock_resp.status = 403
    mock_resp.headers = {}

    challenge_dom = "<html><head><title>Just a Moment...</title></head><body>cf-turnstile</body></html>"

    mock_page = MagicMock()
    mock_page.goto = AsyncMock(return_value=mock_resp)
    mock_page.content = AsyncMock(return_value=challenge_dom)
    mock_page.route = AsyncMock()
    mock_page.close = AsyncMock()

    mock_context = MagicMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_context.close = AsyncMock()

    mock_browser = MagicMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.close = AsyncMock()

    mock_playwright_cm = MagicMock()
    mock_playwright_cm.chromium.launch = AsyncMock(return_value=mock_browser)

    with (
        patch(
            "src.modules.security.services.link_validator_service.LinkValidatorService.validate_url",
            new_callable=AsyncMock,
            return_value=validated_dummy,
        ),
        patch(
            "src.modules.scraping.services.crawler_service.async_playwright"
        ) as mock_ap,
    ):
        mock_ap.return_value.__aenter__.return_value = mock_playwright_cm

        with pytest.raises(AccessChallengeBlockedError) as exc_info:
            await service.crawl_page("https://scholarships.example.edu/blocked")

        assert exc_info.value.code == ERR_ACCESS_CHALLENGE_BLOCKED


# [OMA-W005-T010] Test multi-page article recursion enforces 5-page depth cap (depth <= 4)
@pytest.mark.asyncio
async def test_crawl_page_multipage_depth_cap():
    """Protects UC-09 & TEST-09: Verifies multi-page crawl halts at max_subpages (5 pages total, depth <= 4)."""
    service = CrawlerService()

    validated_dummy = ValidatedUrl(
        original_url="https://scholarships.example.edu/article/part1",
        canonical_url="https://scholarships.example.edu/article/part1",
        scheme="https",
        host="scholarships.example.edu",
        port=443,
        resolved_ip="93.184.216.34",
        is_https=True,
        dns_pinned_rule="--host-resolver-rules=MAP scholarships.example.edu 93.184.216.34",
    )

    # Generate sequential page content with next link on each
    def page_content_generator(url: str):
        # Always includes a link to the "next" subpage
        current_num = 1
        for i in range(1, 10):
            if f"part{i}" in url:
                current_num = i
                break
        next_num = current_num + 1
        return (
            f"<html><body><article><h1>Section {current_num}</h1>"
            f'<div class="page-links"><a class="next" href="/article/part{next_num}">Next</a></div>'
            "</article></body></html>"
        )

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.headers = {}

    current_url = "https://scholarships.example.edu/article/part1"

    async def mock_goto(target_url, **kwargs):
        nonlocal current_url
        current_url = target_url
        return mock_resp

    async def mock_content():
        return page_content_generator(current_url)

    mock_page = MagicMock()
    mock_page.goto = AsyncMock(side_effect=mock_goto)
    mock_page.content = AsyncMock(side_effect=mock_content)
    mock_page.route = AsyncMock()
    mock_page.close = AsyncMock()

    mock_context = MagicMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_context.close = AsyncMock()

    mock_browser = MagicMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.close = AsyncMock()

    mock_playwright_cm = MagicMock()
    mock_playwright_cm.chromium.launch = AsyncMock(return_value=mock_browser)

    with (
        patch(
            "src.modules.security.services.link_validator_service.LinkValidatorService.validate_url",
            new_callable=AsyncMock,
            return_value=validated_dummy,
        ),
        patch(
            "src.modules.scraping.services.crawler_service.async_playwright"
        ) as mock_ap,
    ):
        mock_ap.return_value.__aenter__.return_value = mock_playwright_cm

        res = await service.crawl_page(
            url="https://scholarships.example.edu/article/part1",
            has_multi_page=True,
            max_subpages=5,
        )

        # Enforces hard cap of 5 pages total (depth <= 4)
        assert res.subpage_count == 5
        assert len(res.lineage_records) == 5
        assert res.lineage_records[0]["tree_depth"] == 0
        assert res.lineage_records[-1]["tree_depth"] == 4
        # Verify virtual DOM contains concatenated pages
        assert "Section 1" in res.html
        assert "Section 5" in res.html
        assert "Section 6" not in res.html
