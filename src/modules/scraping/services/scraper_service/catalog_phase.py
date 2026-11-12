# [OMA-W006-T009] Phase 1 Level 1 catalog crawl implementation

import asyncio
import logging
import urllib.parse
from typing import Any

from bs4 import BeautifulSoup

from src.modules.core.database.repositories.scraping_repository import (
    ScrapingRepository,
)
from src.modules.scraping.services.crawler_service import CrawlerService
from src.modules.scraping.services.pagination_service import (
    PaginationService,
    PaginationState,
)

logger = logging.getLogger(__name__)


def extract_cards_from_html(html: str, current_url: str) -> list[dict[str, Any]]:
    """Extracts opportunity card links and previews from catalog HTML."""
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    cards: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    containers = soup.select(
        "article, .card, .post, .scholarship-item, .opportunity-card, .listing-item, [role='article']"
    )
    if not containers:
        containers = soup.find_all("a", href=True)

    for container in containers:
        if container.name == "a":
            anchor = container
        else:
            anchor = container.find("a", href=True)

        if not anchor:
            continue

        href = anchor.get("href", "").strip()
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue

        abs_url = urllib.parse.urljoin(current_url, href)
        clean_url = urllib.parse.urldefrag(abs_url).url

        if clean_url in seen_urls:
            continue

        title = ""
        heading = (
            container.find(["h1", "h2", "h3", "h4"]) if container.name != "a" else None
        )
        if heading:
            title = heading.get_text(strip=True)
        elif anchor.get_text(strip=True):
            title = anchor.get_text(strip=True)

        snippet = ""
        p_tag = container.find("p") if container.name != "a" else None
        if p_tag:
            snippet = p_tag.get_text(strip=True)

        img_url = None
        img_tag = container.find("img") if container.name != "a" else None
        if img_tag and img_tag.get("src"):
            img_url = urllib.parse.urljoin(current_url, str(img_tag.get("src")))

        seen_urls.add(clean_url)
        cards.append(
            {
                "url": clean_url,
                "title": title[:200] if title else None,
                "snippet": snippet[:500] if snippet else None,
                "image_url": img_url,
            }
        )

    return cards


async def crawl_catalog_phase(
    crawler_service: CrawlerService,
    pagination_service: PaginationService,
    repository: ScrapingRepository,
    operation_id: str,
    source: Any,
    config: Any,
    operation_token: asyncio.Event | None,
    source_token: asyncio.Event | None,
) -> int:
    """Crawls Level 1 catalog pages and persists discovered listings into raw_listings."""
    start_url = getattr(source, "url", "")
    if not start_url:
        return 0

    max_pages = (
        getattr(config, "max_pages_per_run", 10)
        if config and config.max_pages_per_run
        else 10
    )
    pagination_type = getattr(config, "pagination_type", "none") if config else "none"
    pagination_config = getattr(config, "pagination_config", {}) if config else {}
    rate_limit_delay = (
        float(getattr(config, "rate_limit_delay_sec", 1.0) or 1.0) if config else 1.0
    )

    state = PaginationState(initial_url=start_url)
    current_url = start_url
    page_num = 1
    total_discovered = 0

    while page_num <= max_pages:
        # Safe cancellation token check
        if (operation_token and operation_token.is_set()) or (
            source_token is not None and source_token.is_set()
        ):
            raise asyncio.CancelledError(f"Catalog crawl halted at page {page_num}")

        logger.info(
            "Crawling catalog page %d: %s (source: %s)",
            page_num,
            current_url,
            source.id,
        )

        crawl_res = await crawler_service.crawl_page(
            url=current_url,
            wait_for_selector=(
                getattr(config, "wait_for_selector", None) if config else None
            ),
            page_timeout_sec=(
                getattr(config, "page_timeout_sec", None) if config else None
            ),
        )

        discovered_cards = extract_cards_from_html(crawl_res.html, current_url)

        if discovered_cards:
            batch_payload = [
                {
                    "operation_id": operation_id,
                    "source_id": source.id,
                    "discovered_url": card["url"],
                    "listing_page_url": current_url,
                    "card_title_preview": card.get("title"),
                    "card_snippet_preview": card.get("snippet"),
                    "card_image_url": card.get("image_url"),
                    "page_number": page_num,
                    "status": "pending_detail_crawl",
                }
                for card in discovered_cards
            ]
            saved_count = await repository.create_listings_batch(
                batch_payload, skip_duplicates=True
            )
            total_discovered += saved_count

        card_identifiers = [c.get("title") or c["url"] for c in discovered_cards]
        step_result = pagination_service.evaluate_step(
            state=state,
            html=crawl_res.html,
            current_url=current_url,
            status_code=crawl_res.status_code,
            card_identifiers=card_identifiers,
            pagination_type=pagination_type,
            pagination_config=pagination_config,
            next_button_selector=None,
            incremental_cutoff_enabled=(
                getattr(config, "incremental_cutoff_enabled", True) if config else True
            ),
        )

        if step_result.is_terminated or not step_result.next_url:
            logger.info(
                "Catalog pagination terminated at page %d (signal: %s)",
                page_num,
                step_result.termination_signal,
            )
            break

        current_url = step_result.next_url
        page_num += 1

        if rate_limit_delay > 0:
            await asyncio.sleep(rate_limit_delay)

    return total_discovered
