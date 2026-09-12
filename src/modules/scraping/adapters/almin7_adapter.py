import logging
import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from src.modules.infrastructure.http.base_http_client import BaseHttpClient
from src.modules.infrastructure.http.exceptions import HttpClientError

from .base_adapter import BaseAdapter

logger = logging.getLogger(__name__)


def get_nested_field(data: dict[str, Any], path: str | None) -> Any:
    """يستخرج قيمة حقل متداخل (nested field) بأمان باستخدام مسار نقطي (dot notation)."""
    if not path or not isinstance(data, dict):
        return None
    current: Any = data
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, (list, tuple)) and part.isdigit():
            idx = int(part)
            current = current[idx] if 0 <= idx < len(current) else None
        else:
            return None
        if current is None:
            return None
    return current


class Almin7Adapter(BaseAdapter):
    """محول خاص بموقع Almin7 للمنح الدراسية والفرص التعليمية عبر HTML Web Scraping."""

    source_name: str = "almin7"
    base_url: str = "https://almin7.com"
    api_endpoint: str = "/scholarship/"

    def __init__(
        self,
        source_config: dict[str, Any] | None = None,
        http_client: BaseHttpClient | None = None,
        source_id: str | None = None,
        source_name: str | None = None,
        base_url: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            source_config=source_config,
            http_client=http_client,
            source_id=source_id,
            source_name=source_name,
            base_url=base_url,
            **kwargs,
        )
        # Force the HTML scraping endpoint, ignoring any stale WordPress config from DB
        self.api_endpoint = "/scholarship/"

    # أنماط استبعاد المقالات والتخصصات غير المرتبطة بالفرص
    EXCLUDED_PATTERNS = [
        re.compile(
            r"(?i)\b(study tips|career advice|نصائح للدراسة|كيف تختار تخصصك|معلومات عامة|أخبار عامة)\b"
        ),
        re.compile(r"(?i)^(ترتيب الجامعات|الدراسة في|دليل الجامعات|تصنيف الجامعات)"),
        re.compile(
            r"(?i)^دراسة\s+(الرياضيات|الطب|الهندسة|الكيمياء|الفيزياء|التسويق|البرمجة|الحاسوب|القانون|الصيدلة)\b"
        ),
    ]
    GENERIC_STUDY_GUIDE_PATTERN = re.compile(r"(?i)^\s*دراسة\s+.+?\s+في\s+.+$")

    EXCLUDED_CATEGORY_PATTERNS = [
        re.compile(
            r"(?i)\b(articles|news|tips|advice|مقالات|أخبار|نصائح|إرشادات|specialization|تخصصات|university-rankings|study-abroad)\b"
        ),
    ]

    OPPORTUNITY_CATEGORY_PATTERNS = [
        re.compile(
            r"(?i)\b(scholarships?|fellowships?|internships?|grants?|training|volunteering|منح|منحة|زمالة|تدريب|تطوع|فرص)\b"
        ),
    ]

    async def fetch(self, limit: int = 20, page: int = 1) -> list[dict[str, Any]]:
        """يجلب فرص المنح من موقع Almin7 عبر HTML Web Scraping مع دعم pagination."""
        all_items: list[dict[str, Any]] = []
        current_page = page
        endpoint = self.api_endpoint or "/scholarship/"
        if not endpoint.startswith("/"):
            endpoint = f"/{endpoint}"
        endpoint = endpoint.rstrip("/")
        # Track seen source URLs to detect duplicate pages (website-side redirect loops)
        seen_urls: set[str] = set()

        while len(all_items) < limit:
            if current_page > 1:
                page_path = f"{endpoint}/page/{current_page}/"
            else:
                page_path = f"{endpoint}/"

            page_url = (
                f"{self.base_url}{page_path}"
                if not page_path.startswith("http")
                else page_path
            )

            try:
                response = await self.http_client.get(page_url)
                html_text = response.text
            except HttpClientError as exc:
                logger.warning(
                    "Failed to fetch HTML page %d for %s: %s",
                    current_page,
                    self.source_name,
                    exc,
                )
                break
            except Exception as exc:
                logger.error(
                    "Unexpected error fetching HTML for %s on page %d: %s",
                    self.source_name,
                    current_page,
                    exc,
                )
                break

            # Safety: if the website redirected /page/N/ back to the homepage,
            # the actual response URL will no longer contain /page/{current_page}/.
            # We only do this check for page > 1 (page 1 never has /page/ in URL).
            if current_page > 1:
                actual_url = str(response.url).lower()
                expected_segment = f"/page/{current_page}"
                if expected_segment not in actual_url:
                    logger.info(
                        "Page %d for %s was redirected away from expected URL "
                        "(actual: %s); stopping pagination.",
                        current_page,
                        self.source_name,
                        actual_url,
                    )
                    break

            soup = BeautifulSoup(html_text, "html.parser")
            cards = soup.find_all(
                "article",
                class_="al7-scholarship-page-card",
            )

            # Fallback: site may have switched CSS class to al7-archive-card.
            # Only accept cards that carry type-scholarship in their class list
            # AND whose primary link points to a /scholarship/ URL path.
            # This mirrors the same discrimination logic used by is_opportunity()
            # and prevents picking up articles/specialization/ranking pages.
            if not cards:
                logger.info(
                    "al7-scholarship-page-card not found on page %d for %s; "
                    "trying al7-archive-card with type-scholarship filter.",
                    current_page,
                    self.source_name,
                )
                candidate_cards = soup.find_all("article", class_="al7-archive-card")
                filtered: list = []
                for candidate in candidate_cards:
                    candidate_classes: list[Any] = candidate.get("class") or []
                    # Must carry WordPress post-type "type-scholarship"
                    if "type-scholarship" not in candidate_classes:
                        continue
                    # Primary link must point to a /scholarship/ URL
                    primary_link = candidate.find("a")
                    href = str(primary_link.get("href", "")) if primary_link else ""
                    if "/scholarship/" not in href:
                        continue
                    filtered.append(candidate)
                cards = filtered

            if not cards:
                logger.info(
                    "No scholarship cards found on page %d for %s; reached end of listings",
                    current_page,
                    self.source_name,
                )
                break

            # Collect URLs on this page to detect duplicate pages
            page_urls: list[str] = []
            for card in cards:
                title_elem = card.find(
                    "h2", class_="al7-archive-posttitle"
                ) or card.find(["h2", "h3", "h1"])
                a_tag = title_elem.find("a") if title_elem else card.find("a")
                if a_tag and a_tag.get("href"):
                    page_urls.append(str(a_tag["href"]).strip())

            # Safety: if every URL on this page was already seen, it's a duplicate page.
            if page_urls and all(u in seen_urls for u in page_urls):
                logger.info(
                    "Page %d for %s contains only duplicate URLs; stopping pagination.",
                    current_page,
                    self.source_name,
                )
                break
            seen_urls.update(page_urls)

            for card in cards:
                # Extract Title & Link
                title_elem = card.find(
                    "h2", class_="al7-archive-posttitle"
                ) or card.find(["h2", "h3", "h1"])
                a_tag = title_elem.find("a") if title_elem else card.find("a")
                if not a_tag or not a_tag.get("href"):
                    continue

                title = a_tag.get_text(strip=True)
                source_url = str(a_tag["href"]).strip()

                # Extract Badge (e.g. منحة, مقال)
                badge_elem = card.find("span", class_="al7-archive-type")
                badge = badge_elem.get_text(strip=True) if badge_elem else ""

                # Extract Excerpt
                excerpt_elem = card.find("p", class_="al7-archive-excerpt")
                excerpt = excerpt_elem.get_text(strip=True) if excerpt_elem else ""

                # Extract Location / Country from card taxline
                tax_elem = card.find("div", class_="al7-archive-taxline")
                country = tax_elem.get_text(strip=True) if tax_elem else ""

                # Extract Date and Application Action URL from card foot
                foot_elem = card.find("div", class_="al7-archive-cardfoot")
                date_str = ""
                action_url = ""
                if foot_elem:
                    date_span = foot_elem.find("span")
                    if date_span:
                        date_str = date_span.get_text(strip=True)
                    action_tag = foot_elem.find("a", class_="al7-archive-action")
                    if action_tag and action_tag.get("href"):
                        action_url = str(action_tag["href"]).strip()

                # Collect taxonomies and categories
                card_classes_raw = card.get("class")
                card_classes: list[str] = (
                    [str(cls) for cls in card_classes_raw]
                    if isinstance(card_classes_raw, list)
                    else []
                )
                categories: list[str] = []
                if badge:
                    categories.append(badge)
                if country and country not in categories:
                    categories.append(country)

                for cls in card_classes:
                    if cls.startswith("opportunitytype-"):
                        categories.append(cls.replace("opportunitytype-", ""))
                    elif cls.startswith("nationality-"):
                        categories.append(cls.replace("nationality-", ""))
                    elif cls.startswith("location-"):
                        categories.append(cls.replace("location-", ""))
                    elif cls.startswith("category-"):
                        categories.append(cls.replace("category-", ""))

                raw_item = {
                    "title": title,
                    "link": source_url,
                    "source_url": source_url,
                    "application_url": action_url,
                    "excerpt": excerpt,
                    "content": excerpt,
                    "published_at": date_str,
                    "country": country,
                    "categories": categories,
                    "badge": badge,
                    "card_classes": card_classes,
                    "raw_html": str(card),
                }

                all_items.append(raw_item)
                if len(all_items) >= limit:
                    break

            current_page += 1

        logger.info(
            "Fetched %d raw items from %s via HTML scraping",
            len(all_items),
            self.source_name,
        )
        return all_items[:limit]

    async def fetch_detail(self, url: str) -> dict[str, Any] | None:
        """Fetch and parse a single Almin7 opportunity detail page."""
        if not url:
            return None

        detail_url = urljoin(f"{self.base_url}/", url)

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/130.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;"
                "q=0.9,image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
            "Referer": f"{self.base_url}/scholarship/",
        }

        try:
            response = await self.http_client.get(
                detail_url,
                headers=headers,
            )
            return self._parse_detail_html(response.text)

        except HttpClientError as exc:
            logger.warning(
                "Failed to fetch Almin7 detail page %s: %s",
                detail_url,
                exc,
            )
        except Exception as exc:
            import traceback

            logger.error(
                "Unexpected error fetching Almin7 detail page %s: %s",
                detail_url,
                exc,
            )
            traceback.print_exc()
        return None

    async def enrich_item(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        """
        Enrich an archive item with data extracted from its detail page.

        The original archive item is preserved if the detail page cannot
        be fetched.
        """
        source_url = str(
            raw_item.get("source_url") or raw_item.get("link") or ""
        ).strip()

        if not source_url:
            return raw_item

        detail = await self.fetch_detail(source_url)

        if not detail:
            return raw_item

        enriched = dict(raw_item)

        if detail.get("title"):
            enriched["detail_title"] = detail["title"]

        if detail.get("content"):
            enriched["detail_html"] = detail["content"]

        if detail.get("text"):
            enriched["detail_text"] = detail["text"]

        if detail.get("application_url"):
            enriched["application_url"] = detail["application_url"]

        if detail.get("country"):
            enriched["detail_country"] = detail["country"]

        if detail.get("organization"):
            enriched["organization"] = detail["organization"]

        if detail.get("fields_of_study"):
            enriched["fields_of_study"] = detail["fields_of_study"]

        if detail.get("study_levels"):
            enriched["study_levels"] = detail["study_levels"]

        if detail.get("funding_type"):
            enriched["funding_type"] = detail["funding_type"]

        if detail.get("funding_details"):
            enriched["funding_details"] = detail["funding_details"]

        if detail.get("deadline"):
            enriched["deadline"] = detail["deadline"]

        if detail.get("eligibility_text"):
            enriched["eligibility_text"] = detail["eligibility_text"]

        if detail.get("eligible_nationalities"):
            enriched["eligible_nationalities"] = detail["eligible_nationalities"]

        return enriched

    async def fetch_with_details(
        self,
        limit: int = 20,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        """
        Fetch archive opportunities and enrich them from their detail pages.

        This is intentionally separate from fetch() so existing tests and
        the current scraping contract remain unchanged.
        """
        items = await self.fetch(limit=limit, page=page)

        enriched_items: list[dict[str, Any]] = []

        for item in items:
            enriched_items.append(await self.enrich_item(item))

        return enriched_items

    def _parse_detail_html(self, html: str) -> dict[str, Any]:
        """Parse structured information from an Almin7 detail page."""
        soup = BeautifulSoup(html, "html.parser")

        content_node = soup.select_one("div.al7-single-content")
        eligibility_text = self._extract_eligibility_text(content_node)
        if not content_node:
            return {}

        title_node = soup.select_one("h1.al7-single-title")
        title = title_node.get_text(" ", strip=True) if title_node else ""

        content_html = str(content_node)
        content_text = content_node.get_text(" ", strip=True)

        application_node = soup.select_one("a.al7-single-apply-beam[href]")
        application_url = (
            str(application_node["href"]).strip() if application_node else None
        )

        taxonomies = self._extract_detail_taxonomies(soup)

        fields_of_study = self._extract_fields_from_detail(content_node)

        study_levels = self._extract_study_levels_from_detail(content_node)

        funding_type, funding_details = self._extract_funding_from_detail(content_node)

        deadline = self._extract_deadline_from_detail(content_node)

        tax_org = taxonomies.get("organization")
        if not tax_org and title:
            clean_t = re.sub(r"^(?:منحة|برنامج|فرصة)\s+", "", title).strip()
            m = re.search(
                r"^(?:جامعة|الجامعة|معهد|المعهد|كلية|الكلية|أكاديمية|الأكاديمية)\s+[^،,–—\n]+",
                clean_t,
            )
            if m:
                tax_org = m.group(0).strip()
            elif clean_t:
                tax_org = clean_t

        return {
            "title": title,
            "content": content_html,
            "text": content_text,
            "application_url": application_url,
            "country": taxonomies.get("country"),
            "organization": tax_org,
            "fields_of_study": fields_of_study,
            "study_levels": study_levels,
            "funding_type": funding_type,
            "funding_details": funding_details,
            "deadline": deadline,
            "eligibility_text": eligibility_text,
            "eligible_nationalities": taxonomies.get("nationalities") or [],
        }

    def _extract_detail_taxonomies(
        self,
        soup: BeautifulSoup,
    ) -> dict[str, Any]:
        """Extract country, university and eligible nationalities."""
        country: str | None = None
        organization: str | None = None
        nationalities: list[str] = []

        nodes = soup.select("span.al7-single-tax-pill, " "a.al7-single-tax-pill")

        for node in nodes:
            anchor = node.find("a", href=True) if node.name != "a" else node

            text = node.get_text(" ", strip=True)

            if anchor:
                href = str(anchor.get("href", "")).lower()
            else:
                href = ""

            node_classes_raw = node.get("class")
            node_classes: list[Any] = (
                node_classes_raw if isinstance(node_classes_raw, list) else []
            )

            classes = " ".join(str(c) for c in node_classes).lower()
            marker = f"{href} {classes}"

            if "nationality" in marker:
                if text and text not in nationalities:
                    nationalities.append(text)

            elif "location" in marker or "/country/" in marker:
                if text and not country:
                    country = text

            elif "university" in marker or "/universities/" in marker:
                if text and not organization:
                    organization = text

        return {
            "country": country,
            "organization": organization,
            "nationalities": nationalities,
        }

    def _extract_eligibility_text(self, content_node: Any) -> str | None:
        """Extract the original eligibility/requirements text from the detail page."""
        section_text = self._get_section_text(
            content_node,
            (
                "شروط التقديم",
                "شروط القبول",
                "متطلبات التقديم",
                "متطلبات القبول",
                "شروط الأهلية",
                "متطلبات الأهلية",
                "معايير الأهلية",
                "من يمكنه التقديم",
                "الأهلية",
                "eligibility",
                "requirements",
                "admission requirements",
            ),
        )

        if section_text:
            return section_text.strip()

        return None

    def _find_section_heading(
        self,
        content_node: Any,
        keywords: tuple[str, ...],
    ) -> Any:
        """Find an h2/h3 heading containing one of the keywords."""
        for heading in content_node.find_all(["h2", "h3"]):
            text = heading.get_text(" ", strip=True)

            if any(keyword in text for keyword in keywords):
                return heading

        return None

    def _get_section_text(
        self,
        content_node: Any,
        keywords: tuple[str, ...],
    ) -> str | None:
        heading = self._find_section_heading(content_node, keywords)

        if not heading:
            return None

        heading_level = int(heading.name[1])

        parts: list[str] = []

        for sibling in heading.find_next_siblings():
            if sibling.name in {"h2", "h3"}:
                sibling_level = int(sibling.name[1])

                if sibling_level <= heading_level:
                    break

            text = sibling.get_text(" ", strip=True)

            if text:
                parts.append(text)

        result = " ".join(parts).strip()

        return result or None

    def _extract_fields_from_detail(
        self,
        content_node: Any,
    ) -> list[str]:
        """Extract actual fields of study from the specialties section."""
        heading = self._find_section_heading(
            content_node,
            ("التخصصات المتاحة", "التخصصات"),
        )

        if not heading:
            return []

        fields: list[str] = []

        for sibling in heading.find_next_siblings():
            if sibling.name == "h2":
                break

            for li in sibling.find_all("li"):
                text = li.get_text(" ", strip=True)

                if not text:
                    continue

                # Example:
                # كلية إدارة الأعمال:
                # إدارة المشاريع، التسويق الرقمي، إدارة الموارد البشرية.
                if ":" in text:
                    text = text.split(":", 1)[1].strip()

                text = re.sub(
                    r"^(تخصصات|التخصصات)\s+",
                    "",
                    text,
                ).strip(" .،,")

                parts = re.split(
                    r"[،,؛;]",
                    text,
                )

                for part in parts:
                    value = part.strip(" .،,؛;")

                    if value and value not in fields:
                        fields.append(value)

        return fields

    def _extract_study_levels_from_detail(
        self,
        content_node: Any,
    ) -> list[str]:
        """
        Extract study levels from meaningful academic text.

        We intentionally do not scan every occurrence of 'دبلوم',
        because it can appear in unrelated text or documents.
        """
        text = content_node.get_text(" ", strip=True).lower()

        levels: list[str] = []

        if re.search(
            r"بكالوريوس|البكالوريوس|طلاب البكالوريوس|"
            r"درجة البكالوريوس|bachelor|undergraduate",
            text,
            re.IGNORECASE,
        ):
            levels.append("Bachelor")

        if re.search(
            r"ماجستير|الماجستير|طلاب الماجستير|"
            r"درجة الماجستير|master|postgraduate|msc",
            text,
            re.IGNORECASE,
        ):
            levels.append("Master")

        if re.search(
            r"دكتوراه|الدكتوراه|طلاب الدكتوراه|" r"درجة الدكتوراه|phd|doctorate",
            text,
            re.IGNORECASE,
        ):
            levels.append("PhD")

        # High School only when the scholarship itself is for high school students
        if re.search(
            r"(?:منحة|دراسة|لطلاب|طلاب)\s+(?:الثانوية|المرحلة الثانوية|high school)",
            text,
            re.IGNORECASE,
        ) and not re.search(r"شهادة الثانوية|وثيقة الثانوية|إتمام الثانوية", text):
            levels.append("High School")

        # Diploma only when explicitly connected to an academic program.
        if re.search(
            r"(?:برنامج|برامج|درجة|طلاب|لطلاب)\s+" r"(?:الدبلوم|دبلوم)",
            text,
            re.IGNORECASE,
        ):
            levels.append("Diploma")

        return levels

    def _extract_funding_from_detail(
        self,
        content_node: Any,
    ) -> tuple[str | None, str | None]:
        """
        Extract funding information from the actual funding section.
        """
        section_text = self._get_section_text(
            content_node,
            (
                "ما الذي تقدمه",
                "التمويل",
                "تغطية",
                "المزايا",
            ),
        )

        if not section_text:
            # Fallback to general content text if no dedicated heading
            full_text = content_node.get_text(" ", strip=True)

            funding_type = self._classify_funding_text(full_text)

            return funding_type, None

        funding_type = self._classify_funding_text(section_text)

        return funding_type, section_text

    def _extract_deadline_from_detail(
        self,
        content_node: Any,
    ) -> str | None:
        """Extract the complete deadline section without inventing dates."""

        section_text = self._get_section_text(
            content_node,
            (
                "المواعيد النهائية",
                "الموعد النهائي",
                "آخر موعد",
                "deadline",
            ),
        )

        return section_text or None

    def _resolve_categories(self, raw_item: dict[str, Any]) -> list[str]:
        """يستخرج التصنيفات سواء كانت من HTML card أو WP-JSON payload."""
        category_names: list[str] = []
        raw_cats = raw_item.get("categories")
        if isinstance(raw_cats, list):
            for c in raw_cats:
                if isinstance(c, str) and c not in category_names:
                    category_names.append(c)

        embedded = raw_item.get("_embedded") or {}
        wp_terms = embedded.get("wp:term") or []
        for term_group in wp_terms:
            if isinstance(term_group, list):
                for term in term_group:
                    if (
                        isinstance(term, dict)
                        and "name" in term
                        and term["name"] not in category_names
                    ):
                        category_names.append(term["name"])

        return category_names

    def parse(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        """Parse and normalize an Almin7 opportunity."""
        raw_title = raw_item.get("title")

        if isinstance(raw_title, dict):
            title = str(raw_title.get("rendered", "")).strip()
        else:
            title = str(raw_title or "").strip()

        raw_content = raw_item.get("content")

        if isinstance(raw_content, dict):
            content = str(raw_content.get("rendered", "")).strip()
        else:
            content = str(raw_content or "").strip()

        raw_excerpt = raw_item.get("excerpt")

        if isinstance(raw_excerpt, dict):
            excerpt = str(raw_excerpt.get("rendered", "")).strip()
        else:
            excerpt = str(raw_excerpt or "").strip()

        # Prefer full detail content when available.
        detail_html = str(raw_item.get("detail_html") or "").strip()

        detail_text = str(raw_item.get("detail_text") or "").strip()

        if detail_html:
            content = detail_html

        description = detail_text or excerpt or content

        source_url = str(
            raw_item.get("source_url") or raw_item.get("link") or ""
        ).strip()

        application_url = str(raw_item.get("application_url") or "").strip() or None

        published_at = raw_item.get("published_at") or raw_item.get("date")

        categories = self._resolve_categories(raw_item)

        opportunity_type = self._determine_opportunity_type(
            title,
            categories,
            content,
        )

        # Prefer detail-page values.
        study_levels = raw_item.get("study_levels")

        if not isinstance(study_levels, list) or not study_levels:
            study_levels = self._extract_study_levels(
                title,
                categories,
                content,
            )

        country = (
            raw_item.get("detail_country")
            or raw_item.get("country")
            or self._extract_country(
                title,
                categories,
                content,
            )
        )

        funding_type = raw_item.get("funding_type") or self._extract_funding_type(
            content
        )

        deadline_text = raw_item.get("deadline")

        if not deadline_text:
            deadline_text = self._extract_deadline_text(content)

        fields_of_study = raw_item.get("fields_of_study")

        if not isinstance(fields_of_study, list):
            fields_of_study = []

        # IMPORTANT:
        # Never use categories as fields_of_study.
        if not fields_of_study:
            fields_of_study = []

        eligibility: dict[str, Any] = {}

        eligibility_text = raw_item.get("eligibility_text")

        nationalities = raw_item.get("eligible_nationalities")

        if isinstance(nationalities, list) and nationalities:
            eligibility["eligible_nationalities"] = nationalities

        # Preserve the full eligibility text so downstream services (cleaning,
        # normalization, matching) can use it.  Must NOT be inferred from prose.
        if isinstance(eligibility_text, str) and eligibility_text.strip():
            eligibility["eligibility_text"] = eligibility_text.strip()

        parsed_output: dict[str, Any] = {
            "title": title,
            "description": description,
            "content": content,
            "source_url": source_url,
            "published_at": published_at,
            "categories": categories,
            "fields_of_study": fields_of_study,
            "opportunity_type": opportunity_type,
            "study_levels": study_levels,
            "country": country,
            "location": country,
            "funding_type": funding_type,
            "deadline": deadline_text,
            "raw_payload": raw_item,
        }

        if isinstance(eligibility_text, str) and eligibility_text.strip():
            parsed_output["eligibility_text"] = eligibility_text.strip()

        if application_url:
            parsed_output["application_url"] = application_url

        organization = raw_item.get("organization")
        if not organization and title:
            clean_t = re.sub(r"^(?:منحة|برنامج|فرصة)\s+", "", title).strip()
            m = re.search(
                r"^(?:جامعة|الجامعة|معهد|المعهد|كلية|الكلية|أكاديمية|الأكاديمية)\s+[^،,–—\n]+",
                clean_t,
            )
            if m:
                organization = m.group(0).strip()
            elif clean_t:
                organization = clean_t

        if organization:
            parsed_output["organization"] = organization

        if eligibility:
            parsed_output["eligibility"] = eligibility

        if raw_item.get("funding_details"):
            parsed_output["funding_details"] = raw_item["funding_details"]

        return parsed_output

    def is_opportunity(self, raw_item: dict[str, Any]) -> bool:
        """
        يحدد هل المقال يمثل فرصة حقيقية أم مقالاً عاماً / تخصصاً بالاعتماد على:
        1. بادج المقال الصريح (مقال vs منحة)
        2. تصنيف الـ post_type من الـ classes
        3. مسار الرابط (استبعاد /specialization/, /category/, إلخ)
        4. فحص التصنيفات والعنوان والكلمات المفتاحية
        """
        badge = str(raw_item.get("badge", "")).strip()
        if badge and ("مقال" in badge or "مقالات" in badge):
            return False

        card_classes = raw_item.get("card_classes") or []
        if isinstance(card_classes, list):
            # If explicit type-post without type-scholarship
            if "type-post" in card_classes and "type-scholarship" not in card_classes:
                return False
            if any(
                c in card_classes
                for c in [
                    "category-articles",
                    "category-specialties",
                    "category-university-rankings",
                    "category-study-abroad",
                ]
            ):
                return False

        # Check source URL path
        url = str(raw_item.get("source_url") or raw_item.get("link") or "").lower()
        if url:
            if any(
                p in url
                for p in [
                    "/specialization/",
                    "/category/",
                    "/university-rankings/",
                    "/study-abroad/",
                    "/blog/",
                    "/articles/",
                ]
            ):
                return False

        parsed = self.parse(raw_item)
        categories = parsed.get("categories", [])
        cat_str = " ".join(str(c) for c in categories)

        # 1. إذا كانت التصنيفات صريحة بالمقالات العامة/الأخبار وبدون تصنيف منحة
        if cat_str:
            has_excluded_cat = any(
                p.search(cat_str) for p in self.EXCLUDED_CATEGORY_PATTERNS
            )
            has_opp_cat = any(
                p.search(cat_str) for p in self.OPPORTUNITY_CATEGORY_PATTERNS
            )
            if has_excluded_cat and not has_opp_cat:
                return False
            if has_opp_cat:
                return True

        # 2. فحص العنوان وأنماط الاستبعاد كـ Fallback
        title = str(parsed.get("title", "")).strip()
        if self.GENERIC_STUDY_GUIDE_PATTERN.search(title):
            return False
        for pattern in self.EXCLUDED_PATTERNS:
            if pattern.search(title):
                return False

        # 3. عندما لا تكون هناك تصنيفات، نشترط وجود مؤشر إيجابي للفرصة في العنوان
        if not cat_str:
            POSITIVE_OPPORTUNITY_PATTERN = re.compile(
                r"(?i)\b(scholarships?|fellowships?|internships?|grants?|training|competition|volunteer|منحة|منح|زمالة|تدريب|تطوع|مسابقة|فرصة)\b"
            )
            return bool(POSITIVE_OPPORTUNITY_PATTERN.search(title))

        return True

    def _determine_opportunity_type(
        self, title: str, categories: list[str], content: str
    ) -> str:
        """يحدد نوع الفرصة باعتماد أولوية العنوان ثم التصنيفات ثم المحتوى باستخدام Word Boundaries."""
        cat_str = " ".join(categories)

        # 1. Check Title First (Highest Priority)
        title_type = self._match_type_pattern(title)
        if title_type:
            return title_type

        # 2. Check Categories
        cat_type = self._match_type_pattern(cat_str)
        if cat_type:
            return cat_type

        # 3. Check Content Body
        content_type = self._match_type_pattern(content[:1000])
        if content_type:
            return content_type

        return "scholarship"

    def _match_type_pattern(self, text: str) -> str | None:
        if not text:
            return None

        # Check fellowship
        if re.search(r"(?i)\b(fellowship|fellowships|fellow|زمالة|زمالات)\b", text):
            return "fellowship"

        # Check internship (word boundary prevents matching 'international')
        if re.search(
            r"(?i)\b(internship|internships|intern|interns|تدريب[ -]?عملي|تدريب[ -]?صيفي|فرصة[ -]?تدريب)\b",
            text,
        ):
            return "internship"

        # Check training / bootcamp / workshop
        if re.search(
            r"(?i)\b(training|trainee|traineeship|bootcamp|workshop|دورة[ -]?تدريبية|برنامج[ -]?تدريبي|معسكر)\b",
            text,
        ):
            return "training"

        # Check volunteering
        if re.search(
            r"(?i)\b(volunteering|volunteer|تطوع|عمل[ -]?تطوعي|فرصة[ -]?تطوع)\b", text
        ):
            return "volunteering"

        # Check exchange program
        if re.search(
            r"(?i)\b(exchange[ -]?(?:program|programme)?|تبادل[ -]?(?:طلابي|ثقافي)?)\b",
            text,
        ):
            return "exchange_program"

        # Check competition
        if re.search(r"(?i)\b(competition|contest|hackathon|مسابقة|هاكاثون)\b", text):
            return "competition"

        # Check grant / research award
        if re.search(r"(?i)\b(grant|grants|منحة[ -]?بحثية|دعم[ -]?مالي)\b", text):
            return "grant"

        # Check scholarship
        if re.search(
            r"(?i)\b(scholarship|scholarships|منحة[ -]?دراسية|منح[ -]?دراسية|منحة|منح)\b",
            text,
        ):
            return "scholarship"

        return None

    def _extract_study_levels(
        self, title: str, categories: list[str], content: str
    ) -> list[str]:
        levels: list[str] = []
        combined = f"{title} {' '.join(categories)} {content[:500]}".lower()

        if any(
            w in combined for w in ["بكالوريوس", "bachelor", "undergraduate", "جامعي"]
        ):
            levels.append("Bachelor")
        if any(w in combined for w in ["ماجستير", "master", "postgraduate", "msc"]):
            levels.append("Master")
        if any(w in combined for w in ["دكتوراه", "phd", "doctorate"]):
            levels.append("PhD")
        if any(w in combined for w in ["ثانوية", "high school"]):
            levels.append("High School")
        if any(w in combined for w in ["دبلوم", "diploma"]):
            levels.append("Diploma")

        return levels

    def _extract_country(
        self, title: str, categories: list[str], content: str
    ) -> str | None:
        combined = f"{title} {' '.join(categories)} {content[:600]}"
        country_regexes = [
            (
                r"(?:في|دولة|منحة)\s+(تركيا|ألمانيا|بريطانيا|كندا|أمريكا|فرنسا|إيطاليا|اليابان|الصين|أستراليا|السعودية|قطر|الإمارات)",
                1,
            ),
            (
                r"(?:in|to)\s+(Turkey|Germany|UK|Canada|USA|France|Italy|Japan|China|Australia)",
                1,
            ),
        ]
        for pattern, group_idx in country_regexes:
            match = re.search(pattern, combined, re.IGNORECASE)
            if match:
                return match.group(group_idx)

        return None

    def _extract_funding_type(self, text: str | None) -> str | None:
        if not text:
            return None

        return self._classify_funding_text(text)

    def _extract_deadline_text(self, content: str) -> str | None:
        patterns = [
            r"(?:آخر موعد للتقديم|اخر موعد|الموعد النهائي)[:\s]+([^<\n\.,;]+)",
            r"(?:deadline|application deadline)[:\s]+([^<\n\.,;]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    def _classify_funding_text(self, text: str) -> str | None:
        """Classify funding from explicit funding language."""
        normalized = re.sub(r"\s+", " ", text).strip().lower()

        # Mixed / tiered funding:
        # Not everyone necessarily receives full funding.
        mixed_patterns = (
            r"كامل(?:ة)?\s+أو\s+جزئي(?:ة)?",
            r"كامل(?:ة)?\s+وجزئي(?:ة)?",
            r"100%\s*.*(?:50%|25%)",
            r"100%\s*.*خصم",
            r"\b(?:15|20|25|30|40|50|60|70|75|80|90)%\s*[-–]?\s*(?:إلى\s*)?(?:15|20|25|30|40|50|60|70|75|80|90)%",
        )

        if any(re.search(pattern, normalized) for pattern in mixed_patterns):
            return "partially_funded"

        # Explicit full tuition coverage.
        full_tuition_patterns = (
            r"ممول(?:ة)?\s+بالكامل",
            r"إعفاء كامل(?: من)?(?: جميع)? الرسوم",
            r"إعفاء كامل من الرسوم الدراسية",
            r"تغطية كاملة(?: ل)?(?: جميع)? الرسوم",
            r"تمويل كامل(?: ل)?(?: جميع)? الرسوم",
            r"منحة كاملة(?: ل)?(?: جميع)? الرسوم",
            r"إعفاء كامل طوال",
            r"تغطية كاملة طوال",
            r"100%\s*(?:من\s*)?الرسوم",
            r"100%\s*تغطية",
        )

        has_full_tuition = any(
            re.search(pattern, normalized) for pattern in full_tuition_patterns
        )

        # Explicit partial tuition coverage.
        partial_patterns = (
            r"تغطية جزئية",
            r"تمويل جزئي",
            r"منحة جزئية",
            r"إعفاء جزئي",
            r"\b(?:[1-9]|[1-9][0-9])%",
        )

        has_partial = any(
            re.search(pattern, normalized) for pattern in partial_patterns
        )

        # Full tuition coverage wins over unrelated discounts
        # such as books, accommodation, or laptops.
        if has_full_tuition:
            return "fully_funded"

        if has_partial:
            return "partially_funded"

        return None
