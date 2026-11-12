# [OMA-W006-T008] Deterministic 3-gate matcher and extraction for TemplateEngineService

import json
import logging
from typing import Any

from bs4 import BeautifulSoup
from prisma.models import ScrapingTemplate

from src.modules.scraping.exceptions import ERR_EXTRACTION_FAILED
from src.modules.scraping.models import ExtractionResult

logger = logging.getLogger(__name__)

COVERAGE_THRESHOLD: float = 0.80
MAX_TEXT_BOUND_CHARS: int = 500_000
CONTAINER_SELECTOR_KEYS: tuple[str, ...] = (
    "card_container",
    "container",
    "item_container",
    "listing_container",
    "root_container",
)


def unwrap_json(raw: Any) -> dict[str, Any]:
    """Safely unwraps Prisma Json, string, or dictionary into a dict."""
    if hasattr(raw, "data"):
        raw = raw.data
    elif hasattr(raw, "_data"):
        raw = raw._data
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return {}
    if isinstance(raw, dict):
        return dict(raw)
    return {}


def extract_selectors_map(schema_dict: dict[str, Any]) -> dict[str, str]:
    """Extracts field-name to CSS-selector mapping from schema selectors or fields."""
    selectors: dict[str, str] = {}
    if "selectors" in schema_dict and isinstance(schema_dict["selectors"], dict):
        for k, v in schema_dict["selectors"].items():
            if isinstance(v, str):
                selectors[k] = v
            elif isinstance(v, dict) and "selector" in v:
                selectors[k] = str(v["selector"])
    elif "selectors" in schema_dict and isinstance(schema_dict["selectors"], list):
        for i, item in enumerate(schema_dict["selectors"]):
            if isinstance(item, str):
                selectors[f"sel_{i}"] = item
            elif isinstance(item, dict) and "selector" in item:
                selectors[item.get("name", f"sel_{i}")] = str(item["selector"])

    if "fields" in schema_dict and isinstance(schema_dict["fields"], dict):
        for k, v in schema_dict["fields"].items():
            if isinstance(v, str):
                selectors[k] = v
            elif isinstance(v, dict) and "selector" in v:
                selectors[k] = str(v["selector"])
    elif "fields" in schema_dict and isinstance(schema_dict["fields"], list):
        for i, item in enumerate(schema_dict["fields"]):
            if isinstance(item, str):
                selectors[f"field_{i}"] = item
            elif isinstance(item, dict) and "selector" in item:
                selectors[item.get("name", f"field_{i}")] = str(item["selector"])

    return selectors


def evaluate_gate_1_container(soup: BeautifulSoup, selectors: dict[str, str]) -> bool:
    """Gate 1: Verifies that the container or primary selector exists in DOM."""
    container_sel = None
    for key in CONTAINER_SELECTOR_KEYS:
        if key in selectors:
            container_sel = selectors[key]
            break

    if container_sel:
        try:
            matches = soup.select(container_sel)
            return len(matches) > 0
        except Exception:
            return False

    primary_sel = (
        selectors.get("title")
        or selectors.get("card_title")
        or selectors.get("content")
        or next(iter(selectors.values()), None)
    )
    if not primary_sel:
        return False

    try:
        primary_matches = soup.select(primary_sel)
        return len(primary_matches) > 0
    except Exception:
        return False


def evaluate_gate_2_coverage(
    soup: BeautifulSoup, selectors: dict[str, str]
) -> tuple[bool, list[str]]:
    """Gate 2: Verifies that >= 80% of candidate fields extract non-empty values."""
    eval_fields = {
        k: sel for k, sel in selectors.items() if k not in CONTAINER_SELECTOR_KEYS
    }
    if not eval_fields:
        eval_fields = selectors

    extracted_texts: list[str] = []
    non_empty_count = 0

    for field_name, sel in eval_fields.items():
        val = extract_first_value(soup, field_name, sel)
        if val:
            non_empty_count += 1
            extracted_texts.append(val)

    total_fields = len(eval_fields)
    coverage = (non_empty_count / total_fields) if total_fields > 0 else 0.0
    return coverage >= COVERAGE_THRESHOLD, extracted_texts


# [OMA-W008-T004] Gate 3: Verifies substantive text content, printable ratio, and bounds
def evaluate_gate_3_text_bounds(extracted_texts: list[str]) -> bool:
    """Gate 3: Verifies extracted non-empty texts are substantive and within bounds."""
    if not extracted_texts:
        return False

    for txt in extracted_texts:
        stripped = txt.strip()
        if len(stripped) < 3:
            return False
        printable_ratio = sum(1 for c in stripped if c.isprintable()) / len(stripped)
        if printable_ratio < 0.8:
            return False
        if len(stripped) > MAX_TEXT_BOUND_CHARS:
            return False

    return True


def extract_first_value(context: BeautifulSoup | Any, field_name: str, sel: str) -> str:
    """Extracts first valid text, href, or src matching selector in context."""
    try:
        nodes = context.select(sel)
    except Exception:
        return ""

    for node in nodes:
        val = ""
        if field_name in {
            "card_link",
            "application_link",
            "link",
            "url",
        } and node.has_attr("href"):
            val = str(node["href"]).strip()
        elif field_name in {
            "card_image",
            "image",
            "image_url",
            "thumbnail",
        } and (node.has_attr("src") or node.has_attr("data-src")):
            val = str(node.get("src") or node.get("data-src", "")).strip()
        else:
            val = node.get_text(strip=True)

        if val:
            return val
    return ""


def match_template_deterministic(
    html: str, templates: list[ScrapingTemplate]
) -> ScrapingTemplate | None:
    """Evaluates incoming HTML against candidate templates ordered by hit count."""
    if not html or not html.strip() or not templates:
        return None

    sorted_templates = sorted(
        templates, key=lambda t: getattr(t, "hit_count", 0) or 0, reverse=True
    )

    soup = BeautifulSoup(html, "html.parser")

    for template in sorted_templates:
        schema = unwrap_json(template.template_schema)
        if not schema:
            continue

        selectors = extract_selectors_map(schema)
        if not selectors:
            continue

        if not evaluate_gate_1_container(soup, selectors):
            continue

        gate_2_passed, extracted_texts = evaluate_gate_2_coverage(soup, selectors)
        if not gate_2_passed:
            continue

        if not evaluate_gate_3_text_bounds(extracted_texts):
            continue

        return template

    return None


def extract_level_1_catalog(
    soup: BeautifulSoup,
    template: ScrapingTemplate,
    selectors: dict[str, str],
) -> ExtractionResult:
    """Extracts Level 1 opportunity cards and discovered URLs."""
    container_sel = (
        selectors.get("card_container")
        or selectors.get("container")
        or selectors.get("item_container")
    )
    card_nodes = soup.select(container_sel) if container_sel else []

    cards: list[dict[str, Any]] = []
    discovered_urls: list[str] = []
    field_results: dict[str, bool] = {}

    for card_el in card_nodes:
        card_item: dict[str, Any] = {}
        for field, sel in selectors.items():
            if field in CONTAINER_SELECTOR_KEYS:
                continue
            val = extract_first_value(card_el, field, sel)
            card_item[field] = val
            if val:
                field_results[field] = True
            elif field not in field_results:
                field_results[field] = False

        title = card_item.get("card_title") or card_item.get("title") or ""
        link = card_item.get("card_link") or card_item.get("link") or ""
        snippet = (
            card_item.get("card_snippet")
            or card_item.get("snippet")
            or card_item.get("description")
            or ""
        )
        img = card_item.get("card_image") or card_item.get("image") or ""

        card_record = {
            "card_title_preview": title,
            "discovered_url": link,
            "card_snippet_preview": snippet,
            "card_image_url": img,
            **card_item,
        }
        cards.append(card_record)
        if link and link not in discovered_urls:
            discovered_urls.append(link)

    if container_sel:
        field_results[container_sel] = len(card_nodes) > 0

    success = len(cards) > 0
    return ExtractionResult(
        url="",
        level=1,
        success=success,
        status="success" if success else "failed",
        data={
            "cards": cards,
            "field_results": field_results,
            "_field_results": field_results,
        },
        discovered_urls=discovered_urls,
        template_id=template.id,
        template_version=template.version,
    )


def extract_level_2_detail(
    soup: BeautifulSoup,
    template: ScrapingTemplate,
    selectors: dict[str, str],
) -> ExtractionResult:
    """Extracts Level 2 scalar educational and grant fields."""
    extracted_data: dict[str, Any] = {}
    field_results: dict[str, bool] = {}

    for field, sel in selectors.items():
        if field in CONTAINER_SELECTOR_KEYS:
            continue
        val = extract_first_value(soup, field, sel)
        extracted_data[field] = val
        field_results[field] = bool(val and val.strip())

    extracted_data["field_results"] = field_results
    extracted_data["_field_results"] = field_results

    has_essential = bool(
        extracted_data.get("title")
        or extracted_data.get("content")
        or any(field_results.values())
    )
    return ExtractionResult(
        url="",
        level=2,
        success=has_essential,
        status="success" if has_essential else "failed",
        data=extracted_data,
        discovered_urls=[],
        template_id=template.id,
        template_version=template.version,
    )


def extract_with_template(html: str, template: ScrapingTemplate) -> ExtractionResult:
    """Extracts catalog cards or detail fields using CSS selectors in template."""
    if not html or not html.strip():
        return ExtractionResult(
            url="",
            level=template.level,
            success=False,
            status="failed",
            error_code=ERR_EXTRACTION_FAILED,
            error_message="HTML content is empty",
            template_id=template.id,
            template_version=template.version,
        )

    try:
        soup = BeautifulSoup(html, "html.parser")
        schema = unwrap_json(template.template_schema)
        selectors = extract_selectors_map(schema)

        if template.level == 1:
            return extract_level_1_catalog(soup, template, selectors)
        return extract_level_2_detail(soup, template, selectors)

    except Exception as exc:
        logger.exception("Extraction failed with template %s: %s", template.id, exc)
        return ExtractionResult(
            url="",
            level=template.level,
            success=False,
            status="failed",
            error_code=ERR_EXTRACTION_FAILED,
            error_message=str(exc),
            template_id=template.id,
            template_version=template.version,
        )
