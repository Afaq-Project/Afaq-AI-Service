import logging
from typing import Any

from src.modules.infrastructure.http.exceptions import (
    HttpClientError,
    HttpResponseError,
)

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


class WordPressApiAdapter(BaseAdapter):
    """محول عام لمصادر WordPress التي تدعم REST API (/wp-json/wp/v2/posts)."""

    source_name: str = "wordpress_api"
    api_endpoint: str = "/wp-json/wp/v2/posts"

    async def fetch(self, limit: int = 20, page: int = 1) -> list[dict[str, Any]]:
        """يجلب المقالات من WordPress REST API مع دعم Pagination والتضمين."""
        endpoint = self.api_endpoint or "/wp-json/wp/v2/posts"
        per_page = self.pagination_config.get("per_page") or min(limit, 50)
        current_page = page
        all_posts: list[dict[str, Any]] = []

        while len(all_posts) < limit:
            remaining = limit - len(all_posts)
            batch_size = min(per_page, remaining)
            params: dict[str, Any] = {
                "_embed": "1",
                "per_page": batch_size,
                "page": current_page,
            }

            # Merge any custom query params from pagination_config
            if "params" in self.pagination_config and isinstance(
                self.pagination_config["params"], dict
            ):
                params.update(self.pagination_config["params"])

            try:
                if self.base_url:
                    url = (
                        f"{self.base_url}{endpoint}"
                        if endpoint.startswith("/")
                        else f"{self.base_url}/{endpoint}"
                    )
                elif endpoint.startswith("http"):
                    url = endpoint
                else:
                    url = (
                        f"https://example.com{endpoint}"
                        if endpoint.startswith("/")
                        else f"https://example.com/{endpoint}"
                    )

                response = await self.http_client.get(url, params=params)
                posts = response.json()
            except HttpResponseError as exc:
                if exc.status_code == 400 and "rest_post_invalid_page_number" in str(
                    exc
                ):
                    # Reached end of pagination
                    break
                logger.warning(
                    "WordPress API error for %s on page %d: %s",
                    self.source_name,
                    current_page,
                    exc,
                )
                break
            except HttpClientError as exc:
                logger.warning(
                    "WordPress API fetch error for %s on page %d: %s",
                    self.source_name,
                    current_page,
                    exc,
                )
                break
            except Exception as exc:
                logger.error(
                    "Unexpected error fetching from %s on page %d: %s",
                    self.source_name,
                    current_page,
                    exc,
                )
                break

            if not isinstance(posts, list) or not posts:
                break

            all_posts.extend(posts)
            current_page += 1

            if len(posts) < batch_size:
                break

        logger.info("Fetched %d raw posts from %s", len(all_posts), self.source_name)
        return all_posts[:limit]

    def parse(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        """يحول منشور WordPress الخام إلى كائن فرصة شبه منظم باستخدام field_mapping."""
        title_path = self.field_mapping.get("title", "title.rendered")
        content_path = self.field_mapping.get("content", "content.rendered")
        excerpt_path = self.field_mapping.get("excerpt", "excerpt.rendered")
        description_path = self.field_mapping.get("description")
        url_path = self.field_mapping.get("url") or self.field_mapping.get(
            "source_url", "link"
        )
        date_path = self.field_mapping.get("date") or self.field_mapping.get(
            "published_at", "date"
        )

        # 1. Resolve Title
        title_val = get_nested_field(raw_item, title_path)
        if title_val is None:
            raw_title = raw_item.get("title")
            title_val = (
                raw_title.get("rendered") if isinstance(raw_title, dict) else raw_title
            )
        title_rendered = str(title_val or "")

        # 2. Resolve Content
        content_val = get_nested_field(raw_item, content_path)
        if content_val is None:
            raw_content = raw_item.get("content")
            content_val = (
                raw_content.get("rendered")
                if isinstance(raw_content, dict)
                else raw_content
            )
        content_rendered = str(content_val or "")

        # 3. Resolve Excerpt
        excerpt_val = get_nested_field(raw_item, excerpt_path)
        if excerpt_val is None:
            raw_excerpt = raw_item.get("excerpt")
            excerpt_val = (
                raw_excerpt.get("rendered")
                if isinstance(raw_excerpt, dict)
                else raw_excerpt
            )
        excerpt_rendered = str(excerpt_val or "")

        # 4. Resolve Description
        desc_val = (
            get_nested_field(raw_item, description_path) if description_path else None
        )
        if isinstance(desc_val, dict):
            desc_val = desc_val.get("rendered", "")
        description = (
            str(desc_val) if desc_val else (excerpt_rendered or content_rendered)
        )

        # 5. Resolve Source URL
        url_val = (
            get_nested_field(raw_item, url_path)
            or raw_item.get("link")
            or raw_item.get("source_url")
            or ""
        )
        source_url = str(url_val)

        # 6. Resolve Date
        published_at = get_nested_field(raw_item, date_path) or raw_item.get("date")

        # 7. Extract categories and tags from _embedded or direct categories list
        category_names: list[str] = []
        raw_cats = raw_item.get("categories")
        if isinstance(raw_cats, list):
            for c in raw_cats:
                if isinstance(c, str):
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

        return {
            "title": title_rendered,
            "description": description,
            "content": content_rendered,
            "source_url": source_url,
            "published_at": published_at,
            "categories": category_names,
            "fields_of_study": category_names,
            "raw_payload": raw_item,
        }
