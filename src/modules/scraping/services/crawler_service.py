# [OMA-W005-T012] [OMA-W005-T013] CrawlerService: Playwright browser lifecycle manager and DOM processor

import asyncio
import gc
import ipaddress
import logging
import re
import shutil
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

from bs4 import BeautifulSoup, Tag
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Response,
    Route,
    async_playwright,
)

from src.modules.core.config.settings import Settings, get_settings
from src.modules.scraping.exceptions import (
    ERR_ACCESS_CHALLENGE_BLOCKED,
    ERR_RATE_LIMITED_COOLDOWN,
    AccessChallengeBlockedError,
    RateLimitedCooldownError,
)
from src.modules.security.services.link_validator_service import LinkValidatorService

logger = logging.getLogger(__name__)

# [OMA-W005-T012] Memory-pruning Chromium launch flags strictly bound to <=1 GB RAM server limit
DEFAULT_CHROMIUM_ARGS = [
    "--disable-dev-shm-usage",
    "--no-zygote",
    "--disable-gpu",
    "--no-sandbox",
    "--single-process",
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-default-apps",
    "--disable-sync",
    "--no-first-run",
]

# [OMA-W005-T012] Known advertising and tracking network domains to block in route handler
TRACKING_DOMAINS = (
    "google-analytics.com",
    "googletagmanager.com",
    "doubleclick.net",
    "facebook.net",
    "connect.facebook.net",
    "adservice.google",
    "adnxs.com",
    "criteo.com",
    "hotjar.com",
    "scorecardresearch.com",
    "clarity.ms",
)

# [OMA-W005-T012] Tokens indicating Cloudflare Turnstile, CAPTCHA, or anti-bot challenge DOMs
BOT_CHALLENGE_INDICATORS = (
    "cf-turnstile",
    "challenges.cloudflare.com",
    "cf-challenge",
    "g-recaptcha",
    "hcaptcha",
    "cf_chl_prog",
    'id="challenge-running"',
    "cf-browser-verification",
    "<title>Just a Moment...</title>",
    "<title>Security Check</title>",
    "Checking your browser before accessing",
)

# [OMA-W005-T013] Client-side JavaScript snippet to unhide tabbed containers
JS_UNHIDE_TABS_SCRIPT = """
() => {
    const selectors = [
        '.tab-pane',
        '[role="tabpanel"]',
        '.tab-content > div',
        '.accordion-collapse',
        '[aria-hidden="true"]',
        '[hidden]'
    ];
    for (const sel of selectors) {
        document.querySelectorAll(sel).forEach(el => {
            el.classList.add('active', 'show', 'in');
            el.classList.remove('fade', 'collapse', 'hidden');
            el.removeAttribute('hidden');
            if (el.getAttribute('aria-hidden') === 'true') {
                el.setAttribute('aria-hidden', 'false');
            }
            el.style.display = 'block';
            el.style.visibility = 'visible';
            el.style.opacity = '1';
            el.style.height = 'auto';
        });
    }
    // Reveal hidden contents in tab panes with inline style display: none
    document.querySelectorAll('.tab-content [style*="none"], [role="tablist"] ~ div [style*="none"]').forEach(el => {
        el.style.display = 'block';
    });
}
"""

# [OMA-W005-T013] Maximum sub-page traversal depth cap (tree depth <= 4, total pages <= 5)
MAX_SUBPAGES_CAP = 5


# [OMA-W005-T012] Data container capturing raw crawler output
@dataclass
class CrawlResult:
    """Raw output from crawler execution."""

    url: str
    canonical_url: str
    status_code: int
    html: str
    resolved_ip: str | None = None
    subpage_count: int = 1
    lineage_records: list[dict[str, Any]] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)
    has_unhidden_tabs: bool = False


# [OMA-W005-T012] [OMA-W005-T013] CrawlerService driver and lifecycle manager
class CrawlerService:
    """Headless Chromium lifecycle manager and DOM extraction service.

    Enforces:
      - Memory-pruning Chromium flags (--disable-dev-shm-usage, --no-zygote, --disable-gpu)
      - Chromium DNS pinning via LinkValidatorService
      - Request interception (Anti-SSRF sub-request blocking & ad-tracker pruning)
      - Sequential single-process concurrency control (max_concurrent_crawls = 1)
      - Client-side multi-tab DOM unhiding (.tab-pane, [role="tabpanel"])
      - Multi-page article virtual DOM concatenation with hard cap of 5 pages (depth <= 4)
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._concurrency_lock = asyncio.Lock()

    # [OMA-W005-T012] Detect local system Chromium executable if Playwright bundled browser is missing
    @classmethod
    def _find_system_executable(cls) -> str | None:
        """Finds system-installed chromium binary path as fallback."""
        return shutil.which("chromium") or shutil.which("google-chrome")

    # [OMA-W005-T012] Build Chromium launch arguments including DNS pinning rules
    @classmethod
    def build_launch_args(
        cls,
        pinned_host: str | None = None,
        pinned_ip: str | None = None,
        extra_args: list[str] | None = None,
    ) -> list[str]:
        """Constructs Chromium command line arguments with memory pruning and DNS pinning."""
        args = list(DEFAULT_CHROMIUM_ARGS)
        if pinned_host and pinned_ip:
            args.append(f"--host-resolver-rules=MAP {pinned_host} {pinned_ip}")
        if extra_args:
            for a in extra_args:
                if a not in args:
                    args.append(a)
        return args

    # [OMA-W005-T012] Detect Cloudflare Turnstile, CAPTCHA, or bot challenge in DOM
    @classmethod
    def detect_access_challenge(cls, html: str) -> bool:
        """Returns True if the HTML payload contains access challenge or bot protection tokens."""
        if not html:
            return False
        lower_html = html.lower()
        return any(
            indicator.lower() in lower_html for indicator in BOT_CHALLENGE_INDICATORS
        )

    # [OMA-W005-T012] Evaluate HTTP status codes for rate-limiting cooldown
    @classmethod
    def check_rate_limit(cls, status_code: int, headers: dict[str, str]) -> None:
        """Inspects response for HTTP 429/503 and triggers RateLimitedCooldownError if delay > 300s."""
        if status_code in (429, 503):
            retry_hdr = headers.get("retry-after") or headers.get("Retry-After")
            retry_seconds = None
            if retry_hdr:
                try:
                    retry_seconds = float(retry_hdr.strip())
                except ValueError:
                    pass

            if retry_seconds is not None and retry_seconds > 300:
                logger.warning(
                    "Rate limit exceeded (HTTP %d) with Retry-After %ss > 300s",
                    status_code,
                    retry_seconds,
                )
                raise RateLimitedCooldownError(
                    f"Target host rate-limited requests (Retry-After: {retry_seconds}s)",
                    code=ERR_RATE_LIMITED_COOLDOWN,
                    cool_down_seconds=retry_seconds,
                    details={
                        "status_code": status_code,
                        "retry_after": retry_seconds,
                    },
                )

    # [OMA-W005-T012] Route handler for sub-request interception (Anti-SSRF & ad blocking)
    @classmethod
    async def _handle_route_interception(
        cls,
        route: Route,
        block_media: bool = True,
    ) -> None:
        """Intercepts outgoing sub-requests to block private IPs, trackers, and heavy media."""
        req = route.request
        req_url = req.url
        parsed = urllib.parse.urlsplit(req_url)
        host = parsed.hostname or ""

        # [OMA-W005-T012] Enforce Anti-SSRF: abort sub-requests attempting to reach private/loopback IPs
        # [OMA-W006-T005] Use public is_ip_blocked helper on LinkValidatorService
        try:
            ipaddress.ip_address(host)
            if LinkValidatorService.is_ip_blocked(host):
                logger.debug("Aborted SSRF sub-request to non-public host: %s", host)
                await route.abort("blockedbyclient")
                return
        except ValueError:
            if host.lower() in (
                "localhost",
                "127.0.0.1",
                "::1",
                "ip6-localhost",
                "ip6-loopback",
            ):
                logger.debug("Aborted SSRF sub-request to loopback host: %s", host)
                await route.abort("blockedbyclient")
                return

        # Block tracking and advertising domains to conserve bandwidth and memory
        lower_host = host.lower()
        if any(tracker in lower_host for tracker in TRACKING_DOMAINS):
            logger.debug("Aborted tracker sub-request: %s", lower_host)
            await route.abort("blockedbyclient")
            return

        # Block heavy media resources if text-only memory mode is enabled
        if block_media and req.resource_type in ("image", "media", "font"):
            await route.abort("blockedbyclient")
            return

        await route.continue_()

    # [OMA-W005-T013] Execute client-side JavaScript to unhide hidden tabbed containers in Playwright
    @classmethod
    async def unhide_tabs_in_page(cls, page: Page) -> None:
        """Executes client-side script in Playwright page to make all tab panels visible."""
        try:
            await page.evaluate(JS_UNHIDE_TABS_SCRIPT)
            logger.debug("Client-side multi-tab unhiding script executed successfully")
        except Exception as e:
            logger.warning("Failed to evaluate multi-tab unhiding script: %s", e)

    # [OMA-W005-T013] DOM-level static unhiding helper using BeautifulSoup
    @classmethod
    def unhide_tabs_in_html(cls, html: str) -> str:
        """Modifies HTML markup to force hidden tab containers into active, visible state.

        Targets .tab-pane, [role="tabpanel"], .accordion-collapse, [aria-hidden="true"],
        and inline display: none / visibility: hidden.
        """
        if not html:
            return ""

        soup = BeautifulSoup(html, "html.parser")
        selector_query = (
            ".tab-pane, [role='tabpanel'], .tab-content > div, "
            ".accordion-collapse, [aria-hidden='true'], [hidden]"
        )

        matched_elements = soup.select(selector_query)
        for el in matched_elements:
            classes = el.get("class", [])
            if isinstance(classes, str):
                classes = classes.split()

            # Add active and show classes
            for add_cls in ("active", "show", "in"):
                if add_cls not in classes:
                    classes.append(add_cls)

            # Remove collapse, fade, hidden classes
            classes = [c for c in classes if c not in ("collapse", "fade", "hidden")]
            el["class"] = classes

            if el.has_attr("hidden"):
                del el["hidden"]

            if el.get("aria-hidden") == "true":
                el["aria-hidden"] = "false"

            # Clean inline style
            style = el.get("style", "")
            if style:
                style = re.sub(
                    r"display\s*:\s*none\s*;?", "display: block;", style, flags=re.I
                )
                style = re.sub(
                    r"visibility\s*:\s*hidden\s*;?",
                    "visibility: visible;",
                    style,
                    flags=re.I,
                )
                el["style"] = style

        return str(soup)

    # [OMA-W005-T013] Extract next sub-page pagination URL from article HTML
    @classmethod
    def extract_subpage_link(
        cls,
        html: str,
        current_url: str,
        subpage_selector: str | None = None,
    ) -> str | None:
        """Extracts the next sub-page link from article HTML."""
        if not html:
            return None

        soup = BeautifulSoup(html, "html.parser")

        # 1. Try explicit user selector if supplied
        if subpage_selector:
            candidate = soup.select_one(subpage_selector)
            if candidate:
                href = candidate.get("href")
                if href and isinstance(href, str) and href.strip() and href != "#":
                    return urllib.parse.urljoin(current_url, href.strip())

        # 2. Try standard sub-page selectors
        common_selectors = [
            "a.next",
            ".nav-links a.next",
            ".pagination .next a",
            ".page-links a.next",
            "a[rel='next']",
            ".page-nav a.next",
        ]
        for sel in common_selectors:
            candidate = soup.select_one(sel)
            if candidate:
                href = candidate.get("href")
                if href and isinstance(href, str) and href.strip() and href != "#":
                    next_url = urllib.parse.urljoin(current_url, href.strip())
                    if next_url != current_url:
                        return next_url

        # 3. Look for links containing "Next Page" or "التالي"
        for a_tag in soup.find_all("a", href=True):
            text = a_tag.get_text(strip=True).lower()
            if text in ("next", "next page", "التالي", "الصفحة التالية", "»"):
                href = a_tag["href"].strip()
                if href and href != "#":
                    next_url = urllib.parse.urljoin(current_url, href)
                    if next_url != current_url:
                        return next_url

        return None

    # [OMA-W005-T013] Concatenate multi-page article bodies into a unified virtual HTML document
    @classmethod
    def concatenate_virtual_dom(cls, pages_html: list[str]) -> str:
        """Concatenates sequential sub-page article bodies into a single virtual HTML document."""
        if not pages_html:
            return ""
        if len(pages_html) == 1:
            return pages_html[0]

        root_soup = BeautifulSoup(pages_html[0], "html.parser")

        # Identify main content container in root document
        root_container = (
            root_soup.find("article")
            or root_soup.find("main")
            or root_soup.find(
                class_=re.compile(
                    r"(entry-content|post-content|article-body|grant-detail)"
                )
            )
            or root_soup.find(id=re.compile(r"(content|main|article)"))
            or root_soup.body
            or root_soup
        )

        for idx, sub_html in enumerate(pages_html[1:], start=2):
            sub_soup = BeautifulSoup(sub_html, "html.parser")
            sub_container = (
                sub_soup.find("article")
                or sub_soup.find("main")
                or sub_soup.find(
                    class_=re.compile(
                        r"(entry-content|post-content|article-body|grant-detail)"
                    )
                )
                or sub_soup.find(id=re.compile(r"(content|main|article)"))
                or sub_soup.body
                or sub_soup
            )

            # Create virtual sub-page wrapper
            wrapper = root_soup.new_tag(
                "div",
                attrs={
                    "class": "afaq-subpage-section",
                    "data-page": str(idx),
                    "data-tree-depth": str(idx - 1),
                },
            )

            # Transfer content
            if isinstance(sub_container, Tag):
                for child in list(sub_container.children):
                    wrapper.append(child)
            else:
                wrapper.append(sub_soup)

            if isinstance(root_container, Tag):
                root_container.append(wrapper)
            else:
                root_soup.append(wrapper)

        return str(root_soup)

    # [OMA-W005-T012] [OMA-W005-T013] Master crawl method with DNS pinning, request interception, and subpage recursion
    async def crawl_page(
        self,
        url: str,
        unhide_tabs: bool = False,
        has_multi_page: bool = False,
        subpage_selector: str | None = None,
        max_subpages: int = MAX_SUBPAGES_CAP,
        wait_for_selector: str | None = None,
        page_timeout_sec: int | None = None,
        block_media: bool = True,
        root_listing_id: str | None = None,
    ) -> CrawlResult:
        """Navigates to URL using headless Chromium, enforcing memory bounds and security constraints.

        Performs:
          1. Pre-navigation URL inspection and Anti-SSRF validation via LinkValidatorService.
          2. Chromium DNS pinning via --host-resolver-rules.
          3. Sub-request interception to prune ad-trackers and private IPs.
          4. Access challenge (Cloudflare/CAPTCHA) and rate limit inspection.
          5. Client-side multi-tab DOM unhiding if requested.
          6. Multi-page article sub-page recursion and virtual DOM concatenation up to max_subpages.
        """
        timeout_ms = (
            page_timeout_sec or self._settings.crawler_page_timeout_sec
        ) * 1000

        # Enforce sequential crawling lock (max_concurrent_crawls = 1)
        async with self._concurrency_lock:
            # Step 1: Validate URL and obtain pinned IP via LinkValidatorService
            validated = await LinkValidatorService.validate_url(
                url, allow_redirects=True
            )
            pinned_host = validated.host
            pinned_ip = validated.resolved_ip

            launch_args = self.build_launch_args(
                pinned_host=pinned_host, pinned_ip=pinned_ip
            )
            exec_path = self._find_system_executable()

            pages_html: list[str] = []
            lineage_records: list[dict[str, Any]] = []
            visited_subpages: set[str] = {validated.canonical_url, url}

            current_target_url = validated.canonical_url
            current_depth = 0
            parent_id: str | None = None
            primary_status_code = 200
            primary_headers: dict[str, str] = {}

            # Browser lifecycle with guaranteed cleanup
            browser: Browser | None = None
            context: BrowserContext | None = None
            page: Page | None = None

            try:
                async with async_playwright() as p:
                    browser = await p.chromium.launch(
                        headless=True,
                        executable_path=exec_path,
                        args=launch_args,
                    )
                    context = await browser.new_context(
                        user_agent=(
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/124.0.0.0 Safari/537.36 AfaqBot/1.0"
                        ),
                        ignore_https_errors=False,
                    )
                    page = await context.new_page()

                    # Set up request interception on page
                    await page.route(
                        "**/*",
                        lambda route: self._handle_route_interception(
                            route=route, block_media=block_media
                        ),
                    )

                    while current_depth < max_subpages:
                        logger.info(
                            "Navigating to %s (tree depth: %d, max: %d)",
                            current_target_url,
                            current_depth,
                            max_subpages,
                        )

                        # Navigate with timeout
                        response: Response | None = await page.goto(
                            current_target_url,
                            wait_until="domcontentloaded",
                            timeout=timeout_ms,
                        )

                        status_code = response.status if response else 200
                        resp_headers = dict(response.headers) if response else {}

                        if current_depth == 0:
                            primary_status_code = status_code
                            primary_headers = resp_headers

                        # Check HTTP 429/503 rate-limiting
                        self.check_rate_limit(status_code, resp_headers)

                        # Wait for specific selector if requested
                        if wait_for_selector:
                            try:
                                await page.wait_for_selector(
                                    wait_for_selector, timeout=5000
                                )
                            except Exception:
                                logger.debug(
                                    "Selector %s not found within 5s", wait_for_selector
                                )

                        # Multi-tab unhiding if requested
                        if unhide_tabs:
                            await self.unhide_tabs_in_page(page)

                        # Capture DOM content
                        html_content = await page.content()

                        # Check for Cloudflare Turnstile / CAPTCHA challenge
                        if self.detect_access_challenge(html_content):
                            logger.warning(
                                "Access challenge detected on %s: raising AccessChallengeBlockedError",
                                current_target_url,
                            )
                            raise AccessChallengeBlockedError(
                                f"Crawl blocked by access challenge on {current_target_url}",
                                code=ERR_ACCESS_CHALLENGE_BLOCKED,
                                details={"url": current_target_url},
                            )

                        # Apply static unhiding fallback to guarantee all attributes match
                        if unhide_tabs:
                            html_content = self.unhide_tabs_in_html(html_content)

                        pages_html.append(html_content)

                        # Record lineage
                        current_page_record = {
                            "url": current_target_url,
                            "tree_depth": current_depth,
                            "parent_id": parent_id,
                            "root_listing_id": root_listing_id,
                            "page_index": current_depth + 1,
                        }
                        lineage_records.append(current_page_record)

                        # Multi-page detail check
                        if not has_multi_page:
                            break

                        next_subpage = self.extract_subpage_link(
                            html=html_content,
                            current_url=current_target_url,
                            subpage_selector=subpage_selector,
                        )

                        if not next_subpage or next_subpage in visited_subpages:
                            break

                        # [OMA-W005-T012] Cross-domain multi-page subpage anti-SSRF security verification
                        subpage_host = (
                            urllib.parse.urlsplit(next_subpage).hostname or ""
                        ).lower()
                        if subpage_host != (pinned_host or "").lower():
                            try:
                                subpage_val = await LinkValidatorService.validate_url(
                                    next_subpage
                                )
                                next_subpage = subpage_val.canonical_url
                            except Exception as subpage_err:
                                logger.warning(
                                    "Multi-page subpage %s navigated across domain to untrusted/invalid host: %s. Halting multi-page traversal.",
                                    next_subpage,
                                    subpage_err,
                                )
                                break

                        if next_subpage in visited_subpages:
                            break

                        # Check hard cap (depth <= 4 / total <= 5)
                        if current_depth + 1 >= max_subpages:
                            logger.warning(
                                "Multi-page article reached maximum cap of %d pages. Halting recursion.",
                                max_subpages,
                            )
                            break

                        visited_subpages.add(next_subpage)
                        parent_id = current_target_url
                        current_target_url = next_subpage
                        current_depth += 1

                    # Concatenate pages into single virtual DOM
                    final_html = self.concatenate_virtual_dom(pages_html)

                    return CrawlResult(
                        url=url,
                        canonical_url=validated.canonical_url,
                        status_code=primary_status_code,
                        html=final_html,
                        resolved_ip=pinned_ip,
                        subpage_count=len(pages_html),
                        lineage_records=lineage_records,
                        headers=primary_headers,
                        has_unhidden_tabs=unhide_tabs,
                    )

            finally:
                # Explicit context and browser cleanup to avoid leaks
                if page:
                    try:
                        await page.close()
                    except Exception:
                        pass
                if context:
                    try:
                        await context.close()
                    except Exception:
                        pass
                if browser:
                    try:
                        await browser.close()
                    except Exception:
                        pass
                # Trigger garbage collection
                gc.collect()
