import logging
import re
from typing import Any

from bs4 import BeautifulSoup

from src.modules.infrastructure.http.exceptions import HttpClientError

from .base_adapter import BaseAdapter

logger = logging.getLogger(__name__)


class Scholars4DevAdapter(BaseAdapter):
    """محول مخصص لموقع Scholars4Dev لجلب المنح الدراسية الدولية."""

    source_name: str = "scholars4dev"
    base_url: str = "https://www.scholars4dev.com"
    api_endpoint: str = "/category/scholarships-list"

    def is_opportunity(self, raw_item: dict[str, Any]) -> bool:
        """يحدد هل المنشور فرصة حقيقية."""
        title = str(
            raw_item.get("title", {}).get("rendered", "")
            if isinstance(raw_item.get("title"), dict)
            else raw_item.get("title", "")
        )
        # Exclude general advice
        if re.search(r"(?i)\b(study tips|how to write|essay advice)\b", title):
            return False
        return True

    async def fetch(self, limit: int = 20, page: int = 1) -> list[dict[str, Any]]:
        """يجلب المقالات من Scholars4Dev إما عبر WP-JSON أو عبر سحب HTML."""
        all_items: list[dict[str, Any]] = []

        # 1. First attempt WP REST API if enabled
        try:
            url = f"{self.base_url}/wp-json/wp/v2/posts"
            response = await self.http_client.get(
                url, params={"per_page": min(limit, 50), "_embed": "1"}
            )
            posts = response.json()
            if isinstance(posts, list) and posts:
                logger.info(
                    "Successfully fetched %d items from scholars4dev via WP REST API",
                    len(posts),
                )
                return posts[:limit]
        except Exception:
            logger.debug(
                "WP REST API not accessible for scholars4dev; falling back to HTML scraping"
            )

        # 2. Fallback to HTML scraping
        current_page = page
        while len(all_items) < limit:
            page_url = (
                f"{self.base_url}/category/scholarships-list/page/{current_page}/"
                if current_page > 1
                else f"{self.base_url}/category/scholarships-list/"
            )
            try:
                response = await self.http_client.get(page_url)
                html_text = response.text
            except HttpClientError as exc:
                logger.warning(
                    "Failed to fetch HTML page %d from scholars4dev: %s",
                    current_page,
                    exc,
                )
                break
            except Exception as exc:
                logger.error("Error fetching scholars4dev HTML: %s", exc)
                break

            soup = BeautifulSoup(html_text, "html.parser")
            posts = soup.find_all("div", class_="post") or soup.find_all("article")
            if not posts:
                posts = soup.find_all("div", class_="entry")

            if not posts:
                break

            for post in posts:
                title_elem = post.find("h2") or post.find("h3") or post.find("h1")
                a_tag = title_elem.find("a") if title_elem else post.find("a")
                if not a_tag or not a_tag.get("href"):
                    continue

                title = a_tag.get_text(strip=True)
                url = a_tag["href"]
                entry_div = post.find("div", class_="entry") or post
                summary = entry_div.get_text(strip=True) if entry_div else ""

                all_items.append(
                    {
                        "title": title,
                        "link": url,
                        "source_url": url,
                        "summary": summary,
                        "content": str(entry_div),
                        "raw_html": str(post),
                    }
                )

                if len(all_items) >= limit:
                    break

            current_page += 1

        logger.info(
            "Fetched %d raw opportunities from %s via HTML parser",
            len(all_items),
            self.source_name,
        )
        return all_items

    def parse(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        """يحلل بيانات منحة scholars4dev ويستخرج المستوى والتمويل والموعد النهائي."""
        title = raw_item.get("title", "")
        if isinstance(title, dict):
            title = title.get("rendered", "")

        content = raw_item.get("content", "")
        if isinstance(content, dict):
            content = content.get("rendered", "")

        summary = raw_item.get("summary") or raw_item.get("excerpt", "")
        if isinstance(summary, dict):
            summary = summary.get("rendered", "")

        source_url = raw_item.get("link") or raw_item.get("source_url", "")
        full_text = f"{title} {summary} {content}"

        # Study levels
        study_levels = self._extract_study_levels(full_text)

        # Funding type
        funding_type = self._extract_funding_type(full_text)

        # Deadline
        deadline = self._extract_deadline(full_text)

        # Country
        country = self._extract_country(full_text)

        # Organization / Host Institution
        organization = self._extract_organization(full_text)

        return {
            "title": title,
            "description": summary or content,
            "content": content or summary,
            "source_url": source_url,
            "opportunity_type": "scholarship",
            "study_levels": study_levels,
            "funding_type": funding_type,
            "deadline": deadline,
            "country": country,
            "location": country,
            "organization": organization,
            "raw_payload": raw_item,
        }

    def _extract_study_levels(self, text: str) -> list[str]:
        levels: list[str] = []
        if re.search(r"(?i)\b(bachelor|undergraduate|bachelors|bsc)\b", text):
            levels.append("Bachelor")
        if re.search(r"(?i)\b(master|masters|postgraduate|msc|mba)\b", text):
            levels.append("Master")
        if re.search(r"(?i)\b(phd|doctorate|doctoral)\b", text):
            levels.append("PhD")
        if re.search(r"(?i)\b(postdoc|postdoctoral)\b", text):
            levels.append("Postdoc")
        return levels

    def _extract_funding_type(self, text: str) -> str | None:
        if re.search(
            r"(?i)\b(fully[ -]?funded|full tuition|comprehensive scholarship|full scholarship)\b",
            text,
        ):
            return "fully_funded"
        if re.search(
            r"(?i)\b(partially[ -]?funded|partial funding|tuition fee waiver|grant)\b",
            text,
        ):
            return "partially_funded"
        if re.search(r"(?i)\b(unfunded|self[ -]?funded)\b", text):
            return "unfunded"
        return None

    def _extract_deadline(self, text: str) -> str | None:
        pattern = re.compile(
            r"(?:deadline|course starts|closes)[:\s]+([^<\n\.,;]+)", re.IGNORECASE
        )
        match = pattern.search(text)
        return match.group(1).strip() if match else None

    def _extract_country(self, text: str) -> str | None:
        countries = [
            "USA",
            "United States",
            "UK",
            "United Kingdom",
            "Canada",
            "Germany",
            "Australia",
            "Netherlands",
            "Sweden",
            "Switzerland",
            "Japan",
            "France",
            "New Zealand",
            "Singapore",
            "South Korea",
            "Belgium",
            "Italy",
        ]
        for country in countries:
            if re.search(rf"\b{re.escape(country)}\b", text, re.IGNORECASE):
                return country
        return None

    def _extract_organization(self, text: str) -> str | None:
        match = re.search(
            r"(?:Host Institution(?:s)?|Provided by|Offered by)[:\s]+([^<\n\.,;]+)",
            text,
            re.IGNORECASE,
        )
        if match:
            return match.group(1).strip()
        univ_match = re.search(r"\b(University of [A-Za-z]+)\b", text, re.IGNORECASE)
        return univ_match.group(1).strip() if univ_match else None
