import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from bs4.element import Tag

from src.modules.infrastructure.http.base_http_client import BaseHttpClient
from src.modules.infrastructure.http.exceptions import HttpClientError
from src.modules.scraping.templates.template_contract import TemplateSchemaValidator

from .base_adapter import BaseAdapter

logger = logging.getLogger(__name__)


class TemplateValidationError(ValueError):
    """Raised when an extraction template is invalid or malformed."""

    pass


class ExtractionError(Exception):
    """Raised when required fields cannot be extracted from the HTML."""

    pass


class GenericTemplateAdapter(BaseAdapter):
    """
    Generic, declarative template-driven adapter for scraping scholarship websites.

    Extracts listings and detail pages based entirely on a JSON configuration template,
    without executing dynamic code or relying on hardcoded selectors.
    """

    def __init__(
        self,
        template: dict[str, Any] | str | Path,
        source_config: dict[str, Any] | None = None,
        http_client: BaseHttpClient | None = None,
        source_id: str | None = None,
        source_name: str | None = None,
        base_url: str | None = None,
        **kwargs: Any,
    ) -> None:
        self.template = self._load_and_validate_template(template)

        resolved_source_name = (
            source_name
            or self.template.get("source_name")
            or (source_config.get("name") if source_config else None)
            or "generic_template"
        )
        resolved_base_url = (
            base_url
            or self.template.get("base_url")
            or (source_config.get("base_url") if source_config else None)
            or ""
        )

        super().__init__(
            source_config=source_config,
            http_client=http_client,
            source_id=source_id,
            source_name=resolved_source_name,
            base_url=resolved_base_url,
            **kwargs,
        )

        self.listing_rules: dict[str, Any] = self.template.get("listing_rules") or {}
        self.detail_rules: dict[str, Any] = self.template.get("detail_rules") or {}

        self.last_listing_fetches: list[Any] = []
        self.last_detail_fetches: list[Any] = []
        self.last_change_detection: Any | None = None
        self.last_listing_html: str | None = None
        self.last_listing_hash: str | None = None

    def _load_and_validate_template(
        self, template_input: dict[str, Any] | str | Path
    ) -> dict[str, Any]:
        """Loads and strictly validates the extraction template schema."""
        if isinstance(template_input, (str, Path)):
            raw_path = Path(template_input)
            if raw_path.is_file():
                try:
                    with open(raw_path, encoding="utf-8") as f:
                        template_dict = json.load(f)
                except Exception as exc:
                    raise TemplateValidationError(
                        f"Failed to read template file '{raw_path}': {exc}"
                    ) from exc
            else:
                try:
                    template_dict = json.loads(str(template_input))
                except Exception as exc:
                    raise TemplateValidationError(
                        f"Invalid template JSON string or non-existent file path: {exc}"
                    ) from exc
        elif isinstance(template_input, dict):
            template_dict = template_input
        else:
            raise TemplateValidationError(
                f"Unsupported template type: {type(template_input)}. Expected dict, str or Path."
            )

        self._validate_template_structure(template_dict)
        return template_dict

    @staticmethod
    def _validate_template_structure(template: dict[str, Any]) -> None:
        """Ensures template conforms strictly to the template contract schema."""
        val_result = TemplateSchemaValidator.validate(template)
        if not val_result.valid:
            error_msgs = "; ".join(e.message for e in val_result.errors)
            raise TemplateValidationError(f"Template validation failed: {error_msgs}")

    def _resolve_url(self, raw_url: str | None) -> str | None:
        """
        Safely resolves a relative or absolute URL against the adapter's base_url.
        Returns None for empty, javascript:, mailto:, data:, tel:, or in-page anchor links.
        """
        if not raw_url or not isinstance(raw_url, str):
            return None

        clean_url = raw_url.strip()
        if not clean_url:
            return None

        lower_url = clean_url.lower()
        if lower_url.startswith(
            ("javascript:", "mailto:", "data:", "tel:", "#")
        ) or clean_url.startswith("#"):
            return None

        if lower_url.startswith(("http://", "https://")):
            return clean_url

        if self.base_url:
            return urljoin(self.base_url.rstrip("/") + "/", clean_url.lstrip("/"))

        return None

    def extract_items_from_listing_html(self, html: str) -> list[dict[str, Any]]:
        """Extracts listing cards from HTML according to listing_rules."""
        if not html or not html.strip():
            return []

        if not self.listing_rules:
            logger.warning("No listing_rules configured for %s", self.source_name)
            return []

        soup = BeautifulSoup(html, "html.parser")
        card_selector = self.listing_rules.get("card_selector", "")
        if not card_selector:
            return []

        cards = soup.select(card_selector)
        items: list[dict[str, Any]] = []

        field_rules: dict[str, Any] = self.listing_rules.get("fields", {})

        for card in cards:
            item_data: dict[str, Any] = {}
            for field_name, rule in field_rules.items():
                val = self._extract_field_value(card, rule)
                item_data[field_name] = val

            raw_card_classes = card.get("class")
            item_data["card_classes"] = (
                [str(c) for c in raw_card_classes]
                if isinstance(raw_card_classes, list)
                else []
            )
            item_data["raw_html"] = str(card)

            if not item_data.get("link") and item_data.get("source_url"):
                item_data["link"] = item_data["source_url"]

            items.append(item_data)

        return items

    def extract_from_detail_html(
        self, html: str, source_url: str = ""
    ) -> dict[str, Any]:
        """Extracts structured fields from a single detail page HTML."""
        if not html or not html.strip():
            return {}

        soup = BeautifulSoup(html, "html.parser")
        extracted: dict[str, Any] = {}

        # 1. Direct field rules
        field_rules: dict[str, Any] = self.detail_rules.get("fields", {})
        for field_name, rule in field_rules.items():
            val = self._extract_field_value(soup, rule)
            if val is not None:
                extracted[field_name] = val
            elif rule.get("required", False):
                raise ExtractionError(
                    f"Required field '{field_name}' not found on detail page"
                )

        # 2. Taxonomies (Country, Organization, Nationalities)
        tax_rules = self.detail_rules.get("taxonomy_rules")
        if tax_rules:
            taxonomies = self._extract_taxonomies(soup, tax_rules)
            if taxonomies.get("country") and not extracted.get("country"):
                extracted["country"] = taxonomies["country"]
            if taxonomies.get("organization") and not extracted.get("organization"):
                extracted["organization"] = taxonomies["organization"]
            if "nationalities" in tax_rules.get("mapping", {}):
                extracted["eligible_nationalities"] = taxonomies.get(
                    "nationalities", []
                )

        # 3. Section rules (Eligibility, Fields of study, Funding, Deadline)
        sec_rules = self.detail_rules.get("section_rules", {})
        for sec_name, s_rule in sec_rules.items():
            sec_val = self._extract_section(soup, s_rule)
            if sec_val:
                if sec_name == "eligibility":
                    extracted["eligibility_text"] = sec_val
                elif sec_name == "funding":
                    extracted["funding_details"] = sec_val
                elif sec_name == "deadline":
                    extracted["deadline"] = sec_val
                elif sec_name == "fields_of_study" and isinstance(sec_val, list):
                    extracted["fields_of_study"] = sec_val

        # Attach source url
        if source_url:
            extracted["source_url"] = source_url

        return extracted

    def _extract_field_value(
        self, context_node: Tag | BeautifulSoup, rule: dict[str, Any]
    ) -> Any:
        """Extracts a value from a node based on selector and extraction type."""
        selector = rule.get("selector")
        if not selector:
            return None

        node = context_node.select_one(selector)
        if not node:
            return None

        extract_type = rule.get("extract", "text")
        if extract_type == "text":
            text = node.get_text(" ", strip=True)
            pattern = rule.get("pattern")
            if pattern and text:
                match = re.search(pattern, text)
                return match.group(1).strip() if match else text
            return text

        if extract_type == "html":
            return str(node)

        if extract_type == "href":
            href_val = node.get("href")
            href_str = href_val[0] if isinstance(href_val, list) else href_val
            return self._resolve_url(href_str)

        if extract_type == "src":
            src_val = node.get("src")
            src_str = src_val[0] if isinstance(src_val, list) else src_val
            return self._resolve_url(src_str)

        if extract_type.startswith("attr:"):
            attr_name = extract_type.split(":", 1)[1]
            return node.get(attr_name)

        return node.get_text(" ", strip=True)

    def _extract_taxonomies(
        self, soup: BeautifulSoup, tax_rules: dict[str, Any]
    ) -> dict[str, Any]:
        """Extracts country, organization, and nationality pills based on generic selectors and URL/class markers."""
        country: str | None = None
        organization: str | None = None
        nationalities: list[str] = []

        container_selector = tax_rules.get("container_selector")
        item_selector = tax_rules.get("item_selector")

        if container_selector:
            container = soup.select_one(container_selector)
            if not container:
                return {
                    "country": None,
                    "organization": None,
                    "nationalities": [],
                }
            nodes = (
                container.select(item_selector)
                if item_selector
                else container.find_all(["a", "span"])
            )
        elif item_selector:
            nodes = soup.select(item_selector)
        else:
            return {
                "country": None,
                "organization": None,
                "nationalities": [],
            }

        mapping = tax_rules.get("mapping", {})

        for node in nodes:
            anchor = node.find("a", href=True) if node.name != "a" else node
            text = node.get_text(" ", strip=True)
            href = str(anchor.get("href", "")).lower() if anchor else ""
            node_classes = node.get("class")
            classes_str = (
                " ".join(str(c) for c in node_classes).lower()
                if isinstance(node_classes, list)
                else ""
            )
            marker = f"{href} {classes_str}"

            # 1. Nationality
            nat_map = mapping.get("nationalities", {})
            if any(m in marker for m in nat_map.get("url_markers", [])) or any(
                m in classes_str for m in nat_map.get("class_markers", [])
            ):
                if text and text not in nationalities:
                    nationalities.append(text)

            # 2. Country
            country_map = mapping.get("country", {})
            if not country and (
                any(m in marker for m in country_map.get("url_markers", []))
                or any(m in classes_str for m in country_map.get("class_markers", []))
            ):
                if text:
                    country = text

            # 3. Organization
            org_map = mapping.get("organization", {})
            if not organization and (
                any(m in marker for m in org_map.get("url_markers", []))
                or any(m in classes_str for m in org_map.get("class_markers", []))
            ):
                if text:
                    organization = text

        # Apply generic dump filtering if configured
        nat_map = mapping.get("nationalities", {})
        if nationalities and nat_map.get("filter_generic_dumps", False):
            generic_list = set(nat_map.get("generic_list", []))
            threshold = int(nat_map.get("generic_threshold", 15))
            overlap = (
                set(nationalities).intersection(generic_list)
                if generic_list
                else set(nationalities)
            )
            is_generic_dump = (
                len(overlap) >= threshold or len(nationalities) >= threshold
            )

            full_text = soup.get_text(" ", strip=True)
            exclude_patterns = nat_map.get("exclude_text_patterns", [])
            has_exclusion = any(
                re.search(pat, full_text, re.IGNORECASE) for pat in exclude_patterns
            )

            if is_generic_dump or has_exclusion:
                specific_patterns = nat_map.get("specific_text_patterns", [])
                found_specific: list[str] = []
                for pat_cfg in specific_patterns:
                    if isinstance(pat_cfg, dict):
                        pat = pat_cfg.get("pattern")
                        val = pat_cfg.get("value")
                        if pat and val and re.search(pat, full_text, re.IGNORECASE):
                            if val not in found_specific:
                                found_specific.append(val)
                nationalities = found_specific

        return {
            "country": country,
            "organization": organization,
            "nationalities": nationalities,
        }

    def _extract_section(
        self, soup: BeautifulSoup, s_rule: dict[str, Any]
    ) -> str | list[str] | None:
        """Finds heading by keywords and extracts text or list items under it."""
        keywords = s_rule.get("heading_keywords", [])
        extract_type = s_rule.get("extract", "section_text")

        heading: Tag | None = None
        for h in soup.find_all(["h1", "h2", "h3", "h4"]):
            h_text = h.get_text(" ", strip=True)
            if any(kw in h_text for kw in keywords):
                heading = h
                break

        if not heading:
            return None

        heading_level = (
            int(heading.name[1])
            if len(heading.name) > 1 and heading.name[1].isdigit()
            else 2
        )

        if extract_type == "section_text":
            parts: list[str] = []
            for sibling in heading.find_next_siblings():
                if sibling.name in {"h1", "h2", "h3", "h4"}:
                    s_level = (
                        int(sibling.name[1])
                        if len(sibling.name) > 1 and sibling.name[1].isdigit()
                        else 2
                    )
                    if s_level <= heading_level:
                        break
                text = sibling.get_text(" ", strip=True)
                if text:
                    parts.append(text)
            res = " ".join(parts).strip()
            return res or None

        if extract_type == "list_items":
            items: list[str] = []
            for sibling in heading.find_next_siblings():
                if sibling.name in {"h1", "h2"}:
                    break
                for li in sibling.find_all("li"):
                    t = li.get_text(" ", strip=True)
                    if not t:
                        continue
                    if ":" in t:
                        t = t.split(":", 1)[1].strip()
                    t = re.sub(r"^(تخصصات|التخصصات)\s+", "", t).strip(" .،,")
                    for part in re.split(r"[،,؛;]", t):
                        val = part.strip(" .،,؛;")
                        if val and val not in items:
                            items.append(val)
            return items

        return None

    def is_opportunity(self, raw_item: dict[str, Any]) -> bool:
        """Evaluates whether the raw scraped item is a valid opportunity or a general article."""
        filter_rules = self.listing_rules.get("opportunity_filter", {})
        if not filter_rules:
            return True

        # Check badge
        badge = str(raw_item.get("badge", "")).strip()
        exclude_badges = filter_rules.get("exclude_badge_keywords", [])
        if badge and any(kw in badge for kw in exclude_badges):
            return False

        # Check card classes
        card_classes = raw_item.get("card_classes") or []
        exclude_classes = filter_rules.get("exclude_classes", [])
        if any(cls in card_classes for cls in exclude_classes):
            return False

        # Check URL patterns
        url = str(raw_item.get("source_url") or raw_item.get("link") or "").lower()
        exclude_urls = filter_rules.get("exclude_url_patterns", [])
        if url and any(p in url for p in exclude_urls):
            return False

        return True

    def parse(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        """
        Parses and standardizes an opportunity into a format consumable by
        CleaningService and NormalizationService.
        """
        raw_title = raw_item.get("title")
        if isinstance(raw_title, dict):
            title = str(raw_title.get("rendered", "")).strip()
        else:
            title = str(raw_title or "").strip()

        if not title and raw_item.get("detail_title"):
            title = str(raw_item.get("detail_title")).strip()

        source_url = str(
            raw_item.get("source_url") or raw_item.get("link") or ""
        ).strip()

        if not title:
            raise ExtractionError("Opportunity title cannot be empty.")

        description = (
            raw_item.get("detail_text")
            or raw_item.get("description")
            or raw_item.get("excerpt")
            or raw_item.get("content")
            or ""
        )
        content = raw_item.get("detail_html") or raw_item.get("content") or description

        eligibility: dict[str, Any] = {}
        if raw_item.get("eligibility_text"):
            eligibility["eligibility_text"] = raw_item["eligibility_text"]
        if raw_item.get("eligible_nationalities"):
            eligibility["eligible_nationalities"] = raw_item["eligible_nationalities"]

        funding_type = raw_item.get("funding_type") or raw_item.get("funding_details")
        deadline = raw_item.get("deadline")

        parsed_output: dict[str, Any] = {
            "title": title,
            "description": str(description).strip(),
            "content": str(content).strip(),
            "source_url": source_url,
            "application_url": raw_item.get("application_url"),
            "organization": raw_item.get("organization"),
            "opportunity_type": raw_item.get("opportunity_type"),
            "funding_type": funding_type,
            "funding_details": raw_item.get("funding_details"),
            "deadline": deadline,
            "country": raw_item.get("country") or raw_item.get("detail_country"),
            "location": raw_item.get("country") or raw_item.get("detail_country"),
            "study_levels": raw_item.get("study_levels") or [],
            "fields_of_study": raw_item.get("fields_of_study") or [],
            "eligibility": eligibility or None,
            "categories": raw_item.get("categories") or [],
            "published_at": raw_item.get("published_at"),
            "raw_payload": raw_item,
        }

        return parsed_output

    async def fetch(self, limit: int = 20, page: int = 1) -> list[dict[str, Any]]:
        """Fetches listings from the source endpoint."""
        from src.modules.scraping.templates.change_detector import PageFetchResult

        self.last_listing_fetches = []
        if not self.base_url:
            return []
        try:
            response = await self.http_client.get(self.base_url)
            html_text = response.text if hasattr(response, "text") else str(response)
            status_code = getattr(response, "status_code", 200)

            self.last_listing_html = html_text
            self.last_listing_hash = hashlib.sha256(
                html_text.encode("utf-8")
            ).hexdigest()

            fetch_res = PageFetchResult(
                url=self.base_url,
                success=True,
                status_code=status_code,
                html=html_text,
            )
            self.last_listing_fetches.append(fetch_res)

            items = self.extract_items_from_listing_html(html_text)
            return items[:limit]
        except Exception as exc:
            fetch_res = PageFetchResult(
                url=self.base_url,
                success=False,
                status_code=getattr(exc, "status_code", None),
                error_type="network_error",
                error_message=str(exc),
                html=None,
            )
            self.last_listing_fetches.append(fetch_res)
            logger.warning("Failed to fetch %s: %s", self.base_url, exc)
            return []

    def has_listing_content_changed(self, previous_hash: str | None) -> bool:
        """Determines if the fetched listing page HTML content has changed compared to previous_hash."""
        if (
            not previous_hash
            or not isinstance(previous_hash, str)
            or not previous_hash.strip()
        ):
            return True
        if not self.last_listing_hash:
            return True
        return self.last_listing_hash != previous_hash.strip()

    async def fetch_with_details(
        self, limit: int = 20, page: int = 1, previous_hash: str | None = None
    ) -> list[dict[str, Any]]:
        """Fetches listings and enriches each with its detail page."""
        from src.modules.scraping.templates.change_detector import PageFetchResult

        self.last_detail_fetches = []
        items = await self.fetch(limit=limit, page=page)
        if previous_hash and not self.has_listing_content_changed(previous_hash):
            logger.info(
                "Listing content unchanged for %s (hash: %s). Skipping detail page fetching.",
                self.source_name,
                previous_hash,
            )
            return []

        enriched: list[dict[str, Any]] = []

        for item in items:
            raw_source_url = item.get("source_url") or item.get("link")
            resolved_url = self._resolve_url(raw_source_url)
            if resolved_url:
                try:
                    res = await self.http_client.get(resolved_url)
                    detail_text = res.text if hasattr(res, "text") else str(res)
                    status_code = getattr(res, "status_code", 200)

                    fetch_res = PageFetchResult(
                        url=resolved_url,
                        success=True,
                        status_code=status_code,
                        html=detail_text,
                    )
                    self.last_detail_fetches.append(fetch_res)

                    detail = self.extract_from_detail_html(
                        detail_text, source_url=resolved_url
                    )
                    enriched_item = dict(item)
                    enriched_item["source_url"] = resolved_url
                    for k, v in detail.items():
                        if v is not None:
                            enriched_item[k] = v
                    enriched.append(enriched_item)
                except Exception as exc:
                    fetch_res = PageFetchResult(
                        url=resolved_url,
                        success=False,
                        status_code=getattr(exc, "status_code", None),
                        error_type=(
                            "network_error"
                            if isinstance(exc, HttpClientError)
                            else "extraction_error"
                        ),
                        error_message=str(exc),
                        html=None,
                    )
                    self.last_detail_fetches.append(fetch_res)
                    logger.warning(
                        "Error fetching detail for %s: %s", resolved_url, exc
                    )
                    enriched.append(item)
            else:
                enriched.append(item)

        return enriched

    def run_change_detection(
        self,
        detail_fetches: list[Any] | None = None,
        listing_fetches: list[Any] | None = None,
        baseline_score: float | None = None,
    ) -> Any:
        """
        Executes template change detection evaluation using stored or provided fetch results.
        """
        from src.modules.scraping.templates.change_detector import (
            TemplateChangeDetector,
        )

        detector = TemplateChangeDetector()
        d_fetches = (
            detail_fetches if detail_fetches is not None else self.last_detail_fetches
        )
        l_fetches = (
            listing_fetches
            if listing_fetches is not None
            else self.last_listing_fetches
        )

        result = detector.evaluate(
            template_input=self.template,
            detail_fetches=d_fetches,
            listing_fetches=l_fetches,
            baseline_score=baseline_score,
        )
        self.last_change_detection = result
        return result
