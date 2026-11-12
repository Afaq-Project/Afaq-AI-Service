# [OMA-W006-T009] Phase 2 Level 2 detail crawl implementation with DTO persistence

import asyncio
import logging
import re
import urllib.parse
import uuid
from typing import Any

from bs4 import BeautifulSoup

from src.modules.core.database.repositories.scraping_repository import (
    GrantDetailCreateInput,
    ScrapingRepository,
)
from src.modules.scraping.services.crawler_service import CrawlerService
from src.modules.scraping.services.document_ingestion_service import (
    DocumentIngestionService,
)
from src.modules.scraping.services.language_classifier_service import (
    LanguageClassifierService,
)

logger = logging.getLogger(__name__)


def is_downloadable_document(url: str) -> bool:
    """Checks if URL path points to a downloadable document (PDF, DOCX, ZIP)."""
    clean = url.split("?")[0].lower()
    return any(
        clean.endswith(ext)
        for ext in (".pdf", ".docx", ".doc", ".xlsx", ".pptx", ".zip")
    )


# [OMA-W007-T005] Query parameter markers for language pairing heuristic
PARAM_LANG_AR: str = "lang=ar"
PARAM_LANG_EN: str = "lang=en"


# [OMA-W007-T003] Prefix unused parameters to satisfy Sonar S1172 while keeping caller compatibility
async def resolve_opportunity_group_id(
    repository: ScrapingRepository,
    source_id: str,
    source_url: str,
    _title: str = "",
    _detected_language: str = "",
    alternate_links: list[str] | None = None,
    **_kwargs: Any,
) -> str:
    """Finds or creates a shared opportunity_group_id UUID for bilingual counterparts."""
    if alternate_links:
        for alt_url in alternate_links:
            existing = await repository.get_grant_detail_by_source_url(
                source_id=source_id, source_url=alt_url
            )
            if existing:
                if existing.opportunity_group_id:
                    return str(existing.opportunity_group_id)
                new_group_id = str(uuid.uuid4())
                await repository.link_opportunity_group(existing.id, new_group_id)
                return new_group_id

    counterpart_url: str | None = None
    if "/ar/" in source_url:
        counterpart_url = source_url.replace("/ar/", "/en/")
    elif "/en/" in source_url:
        counterpart_url = source_url.replace("/en/", "/ar/")
    # [OMA-W007-T005]
    elif PARAM_LANG_AR in source_url:
        counterpart_url = source_url.replace(PARAM_LANG_AR, PARAM_LANG_EN)
    elif PARAM_LANG_EN in source_url:
        counterpart_url = source_url.replace(PARAM_LANG_EN, PARAM_LANG_AR)

    if counterpart_url and counterpart_url != source_url:
        existing = await repository.get_grant_detail_by_source_url(
            source_id=source_id, source_url=counterpart_url
        )
        if existing:
            if existing.opportunity_group_id:
                return str(existing.opportunity_group_id)
            new_group_id = str(uuid.uuid4())
            await repository.link_opportunity_group(existing.id, new_group_id)
            return new_group_id

    return str(uuid.uuid4())


def extract_details_from_html(html: str, source_url: str) -> dict[str, Any]:
    """Extracts structured and rich text details from scholarship HTML."""
    if not html:
        return {"url": source_url, "title": "", "body": ""}

    soup = BeautifulSoup(html, "html.parser")

    title = ""
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True)
    elif soup.title and soup.title.string:
        title = soup.title.string.strip()

    article = (
        soup.find("article")
        or soup.find("main")
        or soup.find(
            class_=re.compile(r"(entry-content|post-content|article-body|grant-detail)")
        )
        or soup.body
    )
    body_text = article.get_text(separator="\n", strip=True) if article else ""

    apply_url = None
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True).lower()
        if any(
            keyword in text
            for keyword in (
                "apply",
                "application",
                "official",
                "portal",
                "register",
                "تقديم",
                "سجل",
                "رابط",
            )
        ):
            apply_url = urllib.parse.urljoin(source_url, str(a.get("href")))
            break

    # Safe dereference of hero_img
    image_url = None
    hero_img = soup.find(
        "img",
        class_=re.compile(r"(hero|featured|attachment|post-thumbnail)"),
    )
    if hero_img is not None and hasattr(hero_img, "get"):
        src_val = hero_img.get("src")
        if src_val:
            image_url = urllib.parse.urljoin(source_url, str(src_val))

    alternate_links: list[str] = []
    for link_tag in soup.find_all("link", rel=re.compile(r"alternate", re.I)):
        hreflang = str(link_tag.get("hreflang", "")).lower()
        if hreflang in ("ar", "en", "en-us", "ar-sa") and link_tag.get("href"):
            alternate_links.append(
                urllib.parse.urljoin(source_url, str(link_tag["href"]))
            )
    for a_tag in soup.find_all("a", href=True):
        cls_name = (
            " ".join(a_tag.get("class", []))
            if isinstance(a_tag.get("class"), list)
            else str(a_tag.get("class", ""))
        )
        text = a_tag.get_text(strip=True).lower()
        if "lang" in cls_name.lower() or text in (
            "english",
            "العربية",
            "ar",
            "en",
        ):
            alternate_links.append(urllib.parse.urljoin(source_url, str(a_tag["href"])))

    return {
        "url": source_url,
        "title": title,
        "body": body_text[:20000],
        "application_url": apply_url,
        "image_url": image_url,
        "alternate_links": list(set(alternate_links)),
    }


# [OMA-W008-T003] Crawl Level 2 detail pages with batch pagination drainage loop
async def crawl_details_phase(
    crawler_service: CrawlerService,
    language_classifier: LanguageClassifierService,
    document_ingestion: DocumentIngestionService | None,
    repository: ScrapingRepository,
    operation_id: str,
    source: Any,
    config: Any,
    operation_token: asyncio.Event | None,
    source_token: asyncio.Event | None,
) -> int:
    """Crawls Level 2 detail pages for pending listings and stores raw_grant_details."""
    rate_limit_delay = (
        float(getattr(config, "rate_limit_delay_sec", 1.0) or 1.0) if config else 1.0
    )
    extracted_count = 0
    seen_ids: set[str] = set()

    while True:
        # Check cancellation tokens
        if (operation_token and operation_token.is_set()) or (
            source_token is not None and source_token.is_set()
        ):
            raise asyncio.CancelledError(f"Details crawl halted for source {source.id}")

        if hasattr(repository, "get_pending_raw_listings"):
            pending_listings = await repository.get_pending_raw_listings(
                source.id, limit=100
            )
        else:
            pending_listings = await repository.get_pending_listings_for_source(
                source.id, limit=100
            )

        new_listings = [item for item in pending_listings if item.id not in seen_ids]
        if not new_listings:
            break

        for listing in new_listings:
            seen_ids.add(listing.id)

            # Re-check cancellation tokens inside inner loop
            if (operation_token and operation_token.is_set()) or (
                source_token is not None and source_token.is_set()
            ):
                raise asyncio.CancelledError(
                    f"Details crawl halted for source {source.id}"
                )

            logger.info(
                "Crawling detail page: %s (listing: %s)",
                listing.discovered_url,
                listing.id,
            )

            try:
                crawl_res = await crawler_service.crawl_page(
                    url=listing.discovered_url,
                    unhide_tabs=(
                        getattr(config, "has_multi_tab_details", False)
                        if config
                        else False
                    ),
                    has_multi_page=(
                        getattr(config, "has_multi_page_details", False)
                        if config
                        else False
                    ),
                    subpage_selector=(
                        getattr(config, "subpage_pagination_selector", None)
                        if config
                        else None
                    ),
                    wait_for_selector=(
                        getattr(config, "wait_for_selector", None) if config else None
                    ),
                    page_timeout_sec=(
                        getattr(config, "page_timeout_sec", None) if config else None
                    ),
                    root_listing_id=listing.id,
                )

                extracted_data = extract_details_from_html(
                    crawl_res.html, listing.discovered_url
                )

                lang_res = language_classifier.classify_opportunity(
                    title=extracted_data.get("title"),
                    description=extracted_data.get("body"),
                )

                # [OMA-W007-T003]
                group_id = await resolve_opportunity_group_id(
                    repository=repository,
                    source_id=source.id,
                    source_url=listing.discovered_url,
                    _title=extracted_data.get("title", ""),
                    _detected_language=lang_res.overall_language,
                    alternate_links=extracted_data.get("alternate_links", []),
                )

                attachment_s3_key: str | None = None
                attachment_metadata: dict[str, Any] | None = None
                has_attachment = False
                app_url = extracted_data.get("application_url")
                if app_url and is_downloadable_document(app_url) and document_ingestion:
                    try:
                        doc_res = await document_ingestion.ingest_document(
                            attachment_url=app_url,
                            source_id=source.id,
                        )
                        attachment_s3_key = doc_res.s3_key
                        attachment_metadata = doc_res.to_dict()
                        has_attachment = True
                    except Exception as doc_exc:
                        logger.warning(
                            "Attachment ingestion failed for %s: %s",
                            app_url,
                            doc_exc,
                        )

                # Persist raw grant detail using GrantDetailCreateInput DTO
                detail_input = GrantDetailCreateInput(
                    operation_id=operation_id,
                    source_id=source.id,
                    source_url=listing.discovered_url,
                    raw_payload=extracted_data,
                    listing_id=listing.id,
                    opportunity_group_id=group_id,
                    image_url=extracted_data.get("image_url"),
                    title_language=lang_res.title_language,
                    body_language=lang_res.body_language,
                    language_confidence=lang_res.overall_confidence,
                    final_application_url=app_url,
                    has_attachment=has_attachment,
                    attachment_s3_key=attachment_s3_key,
                    attachment_metadata=attachment_metadata,
                    status="pending",
                )
                await repository.create_grant_detail(detail_input)

                await repository.mark_listing_extracted(listing.id)
                extracted_count += 1

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "Extraction failed for listing %s (%s): %s",
                    listing.id,
                    listing.discovered_url,
                    exc,
                )
                err_code = getattr(exc, "code", "ERR_DETAIL_EXTRACTION_FAILED")
                await repository.record_listing_failure(
                    listing_id=listing.id,
                    error_message=str(exc),
                    error_code=err_code,
                    max_retries=3,
                )

            if rate_limit_delay > 0:
                await asyncio.sleep(rate_limit_delay)

    return extracted_count


# [OMA-W008-T003] Backward compatible alias
_crawl_details_phase = crawl_details_phase
