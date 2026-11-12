# [OMA-W006-T007] DOM skeletonizer and noise reduction for discovery service

import logging
from typing import Any

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

logger = logging.getLogger(__name__)

HTML_PARSER = "html.parser"

# Tags to strip during aggressive DOM skeletonization
NOISE_TAGS = {
    "script",
    "style",
    "svg",
    "noscript",
    "iframe",
    "header",
    "footer",
    "nav",
    "aside",
    "video",
    "audio",
    "canvas",
    "meta",
    "link",
    "symbol",
    "picture",
    "source",
    "map",
    "track",
}

# Attributes retained for structural and CSS selector synthesis
PRESERVED_ATTRIBUTES = {
    "id",
    "class",
    "href",
    "src",
    "role",
    "type",
    "name",
    "rel",
    "title",
    "aria-label",
    "aria-labelledby",
    "data-page",
}


def collapse_repetitive_elements(soup: BeautifulSoup, max_keep: int = 2) -> None:
    """Collapses repetitive child items (cards, list items, articles) to representative samples."""
    for container in list(soup.find_all(True)):
        children = [c for c in container.children if isinstance(c, Tag)]
        if len(children) < 3:
            continue

        groups: dict[tuple[str, tuple[str, ...]], list[Tag]] = {}
        for c in children:
            cls_tuple = tuple(sorted(c.get("class", [])))
            sig = (c.name, cls_tuple)
            groups.setdefault(sig, []).append(c)

        for _sig, matching_tags in groups.items():
            if len(matching_tags) >= 3:
                for tag_to_remove in matching_tags[max_keep:]:
                    tag_to_remove.decompose()


# [OMA-W007-T003] Prefix unused parameter to satisfy Sonar S1172 while preserving kwargs compatibility
def skeletonize_dom(
    html: str,
    _target_min_bytes: int = 3000,
    target_max_bytes: int = 8000,
    **_kwargs: Any,
) -> str:
    """Compresses raw DOM down to 3–8 KB by stripping noise, comments, inline media, and collapsing cards."""
    if not html or not isinstance(html, str) or not html.strip():
        return ""

    soup = BeautifulSoup(html, HTML_PARSER)

    # 1. Remove noise tags
    for t in list(soup.find_all(list(NOISE_TAGS))):
        t.decompose()

    # 2. Remove HTML comments using non-deprecated string= argument
    for comment in list(soup.find_all(string=lambda t: isinstance(t, Comment))):
        comment.extract()

    # 3. Clean non-essential attributes and strip data URIs
    for tag in list(soup.find_all(True)):
        tag.attrs = {
            k: v for k, v in tag.attrs.items() if k.lower() in PRESERVED_ATTRIBUTES
        }
        src = tag.get("src")
        if isinstance(src, str) and src.lower().startswith("data:"):
            tag["src"] = ""

    # 4. Collapse repetitive cards to 2 representative items
    collapse_repetitive_elements(soup, max_keep=2)

    # 5. Remove empty elements
    void_tags = {"br", "hr", "img", "input"}
    for tag in list(soup.find_all(True)):
        if tag.name not in void_tags:
            if not tag.contents and not tag.get_text(strip=True):
                tag.decompose()

    # 6. Truncate long text nodes using non-deprecated string= argument
    for text_node in list(
        soup.find_all(
            string=lambda t: isinstance(t, NavigableString)
            and not isinstance(t, Comment)
        )
    ):
        text_str = text_node.strip()
        if len(text_str) > 120:
            text_node.replace_with(text_str[:120] + "...")

    result = str(soup)
    result_bytes = result.encode("utf-8")

    # 7. Check target bounds; apply second-pass aggressive pruning if exceeding max
    if len(result_bytes) > target_max_bytes:
        collapse_repetitive_elements(soup, max_keep=1)
        for text_node in list(
            soup.find_all(
                string=lambda t: isinstance(t, NavigableString)
                and not isinstance(t, Comment)
            )
        ):
            text_str = text_node.strip()
            if len(text_str) > 40:
                text_node.replace_with(text_str[:40] + "...")
        result = str(soup)
        result_bytes = result.encode("utf-8")

    if len(result_bytes) > target_max_bytes:
        sliced = result_bytes[:target_max_bytes].decode("utf-8", errors="ignore")
        result = str(BeautifulSoup(sliced, HTML_PARSER))

    return result
