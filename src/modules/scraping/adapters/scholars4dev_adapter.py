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

                processed_items: list[dict[str, Any]] = []

                for post in posts:
                    if self._is_roundup_post(post):
                        split_items = self._split_roundup_post(post)

                        for item in split_items:
                            item_url = item.get("link")

                            if item_url:
                                try:
                                    page_response = await self.http_client.get(item_url)

                                    item["content"] = {
                                        "rendered": page_response.text,
                                    }

                                except Exception as exc:
                                    logger.warning(
                                        "Failed to fetch individual Scholars4Dev page %s: %s",
                                        item_url,
                                        exc,
                                    )

                            processed_items.append(item)
                    else:
                        processed_items.append(post)

                    if len(processed_items) >= limit:
                        break

                logger.info(
                    "Processed %d Scholars4Dev items after roundup splitting",
                    len(processed_items),
                )

                return processed_items[:limit]
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
    def _extract_labeled_section(
        self,
        html: str,
        label_patterns: list[str],
    ) -> str | None:
        soup = BeautifulSoup(html, "html.parser")

        for label in soup.find_all(["strong", "b"]):
            label_text = label.get_text(" ", strip=True)

            # إزالة : والمسافات الزائدة من نهاية الـ label
            normalized_label = re.sub(
                r"[:：]\s*$",
                "",
                label_text,
            ).strip()

            matched = False

            for pattern in label_patterns:
                if re.fullmatch(
                    pattern,
                    normalized_label,
                    re.IGNORECASE,
                ):
                    matched = True
                    break

            if not matched:
                continue

            parent = label.find_parent("p")

            if not parent:
                continue

            sibling = parent.find_next_sibling()

            while sibling:
                sibling_text = sibling.get_text(" ", strip=True)

                if sibling_text:
                    return sibling_text

                sibling = sibling.find_next_sibling()

        return None


    def _extract_fields_of_study(self, html: str) -> list[str]:
        """Extract fields of study from explicit Scholars4Dev labels."""
        section = self._extract_labeled_section(
            html,
            [
                r"Field\(s\) of study",
                r"Field of study",
                r"Level/Field\(s\) of study",
                r"Level/Fields of study",
                r"Level/Field of study",
                r"Fields of study/Programmes",
            ],
        )

        if not section:
            return []

        normalized = section.strip()

        if re.search(
            r"\b(any subject|all subjects|all fields|any field)\b",
            normalized,
            re.IGNORECASE,
        ):
            return ["All fields"]

        # "Online" alone is not a field of study.
        if normalized.lower() == "online":
            return []

        return [normalized]
    def _is_roundup_post(self, raw_item: dict[str, Any]) -> bool:
        """يحدد هل المنشور عبارة عن قائمة/تجميعة فرص متعددة."""

        title = raw_item.get("title", "")

        if isinstance(title, dict):
            title = title.get("rendered", "")

        title = BeautifulSoup(
            str(title),
            "html.parser",
        ).get_text(" ", strip=True)

        roundup_patterns = (
            r"\bfully funded scholarships\b",
            r"\btop \d+ scholarships\b",
            r"\b\d+\+ scholarships\b",
            r"\blist of scholarships\b",
            r"\bbest scholarships\b",
        )

        return any(
            re.search(pattern, title, re.IGNORECASE)
            for pattern in roundup_patterns
        )
    def _split_roundup_post(
        self,
        raw_item: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """
        Split a Scholars4Dev roundup/list post into individual opportunities.

        Each opportunity is represented as a separate raw item so the existing
        scraping -> parsing -> cleaning pipeline can remain unchanged.
        """
        content = raw_item.get("content", "")

        if isinstance(content, dict):
            content = content.get("rendered", "")

        if not content:
            return [raw_item]

        soup = BeautifulSoup(content, "html.parser")

        opportunities: list[dict[str, Any]] = []

        for paragraph in soup.find_all("p"):
            # Ignore "See also" blocks and other navigation content.
            if paragraph.find_parent("blockquote"):
                continue

            link = paragraph.find("a", href=True)
            strong = paragraph.find(["strong", "b"])

            if not link or not strong:
                continue

            title = link.get_text(" ", strip=True)

            if not title:
                continue

            # The opportunity title is usually inside <strong><a>...</a></strong>.
            strong_link = strong.find("a", href=True)

            if not strong_link:
                continue

            title = strong_link.get_text(" ", strip=True)

            if not title:
                continue

            # Make sure this is an actual opportunity block.
            # We expect descriptive text after the title.
            paragraph_text = paragraph.get_text(" ", strip=True)

            if len(paragraph_text) <= len(title):
                continue

            opportunity_url = strong_link.get("href")

            if not opportunity_url:
                continue

            # Ignore obvious navigation links.
            lower_title = title.lower()

            if lower_title in {
                "see also",
                "read more",
                "click here",
            }:
                continue

            opportunity_payload = dict(raw_item)

            opportunity_payload["title"] = {
                "rendered": title,
            }

            opportunity_payload["link"] = opportunity_url
            opportunity_payload["source_url"] = opportunity_url

            opportunity_payload["summary"] = {
                "rendered": paragraph_text,
            }

            opportunity_payload["content"] = {
                "rendered": str(paragraph),
            }

            # Keep the original roundup URL for traceability.
            opportunity_payload["roundup_source_url"] = (
                raw_item.get("link")
                or raw_item.get("source_url")
            )

            opportunity_payload["is_split_from_roundup"] = True

            opportunities.append(opportunity_payload)

        if not opportunities:
            return [raw_item]


        return opportunities


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
        # Fields of study
        fields_of_study = self._extract_fields_of_study(content)

        # Funding type
        funding_type = self._extract_funding_type(content)

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
            "fields_of_study": fields_of_study,
            "funding_type": funding_type,
            "deadline": deadline,
            "country": country,
            "location": country,
            "organization": organization,
            "raw_payload": raw_item,
        }

    def _extract_study_levels(self, text: str) -> list[str]:
        """Extract study levels from the explicit level section first."""

        levels: list[str] = []

        # Scholars4Dev may put the study level directly in the page summary,
        # e.g. "Masters/PhD Degrees", instead of inside Field(s) of study.
        if re.search(
            r"(?i)\bmasters?\s*/\s*phd\s+degrees\b",
            text,
        ):
            return ["Master", "PhD"]

        section = self._extract_labeled_section(
            text,
            [
                r"Level/Field\(s\) of study",
                r"Level/Fields of study",
                r"Level/Field of study",
                r"Field\(s\) of study",
                r"Field of study",
                r"Fields of study/Programmes",
            ],
        )

        source_text = section or text

        # VLIR-UOS lists multiple programme levels in separate HTML blocks.
        # The first extracted section may contain only "Professional Bachelors",
        # while the same programme list also contains Initial and Advanced Masters.
        if re.search(
            r"(?i)\bProfessional Bachelors\b",
            text,
        ) and re.search(
            r"(?i)\bInitial masters\b",
            text,
        ):
            return ["Bachelor", "Master"]

        # Bachelor
        if re.search(
            r"(?i)\b(bachelor|undergraduate|bachelors|bsc)\b",
            source_text,
        ):
            levels.append("Bachelor")

        # Master
        # "Postgraduate" alone is not enough to classify an opportunity as Master.
        # Some postgraduate research opportunities are PhD-only.
        if re.search(
            r"(?i)\b(master|masters|msc|mba)\b",
            source_text,
        ):
            levels.append("Master")

        # PhD
        if re.search(
            r"(?i)\b(phd|doctorate|doctoral)\b",
            source_text,
        ):
            levels.append("PhD")

        # Postdoc
        if re.search(
            r"(?i)\b(postdoc|postdoctoral)\b",
            source_text,
        ):
            levels.append("Postdoc")

        return levels
    def _extract_funding_type(self, html: str) -> str | None:
        """Extract funding type from explicit scholarship funding text."""

        text = BeautifulSoup(html, "html.parser").get_text(
            " ", strip=True
        )

        if re.search(
            r"(?i)\btuition\b",
            text,
        ) and re.search(
            r"(?i)\b(airfare|travel)\b",
            text,
        ) and re.search(
            r"(?i)\b(living stipend|stipend|living allowance|grant for living costs)\b",
            text,
        ):
            return "fully_funded"

        if re.search(
            r"(?i)\b(fully[ -]?funded|full[- ]cost|full tuition|comprehensive scholarship|full scholarship|full scholarships)\b",
            text,
        ):
            return "fully_funded"
        if re.search(
            r"(?i)\btuition and college fees in full\b",
            text,
        ):
            return "fully_funded"
        if re.search(
                r"(?i)\bfull payment of your academic fees\b",
                text,
            ) and re.search(
                r"(?i)\bmaintenance stipend\b",
                text,
            ):
                return "fully_funded"
        if re.search(
            r"(?i)\b(partially[ -]?funded|partial funding|tuition fee waiver)\b",
            text,
        ):
            return "partially_funded"

        if re.search(
            r"(?i)\b(unfunded|self[ -]?funded)\b",
            text,
        ):
            return "unfunded"

        return None

    def _extract_deadline(self, html: str) -> str | None:
        """Extract deadline from an explicit Deadline label."""

        soup = BeautifulSoup(html, "html.parser")

        # First, look for the explicit Deadline label.
        for label in soup.find_all(["strong", "b"]):
            label_text = label.get_text(" ", strip=True)

            normalized_label = re.sub(
                r"[:：]\s*$",
                "",
                label_text,
            ).strip()

            if not re.fullmatch(
                r"Deadline",
                normalized_label,
                re.IGNORECASE,
            ):
                continue

            parent = label.find_parent("p")

            if not parent:
                continue

            parent_text = parent.get_text(" ", strip=True)

            match = re.search(
                r"(?i)\bDeadline\s*[:：]\s*(.*?)(?=\s+Study in:|\s+Course starts\b|$)",
                parent_text,
            )

            if match:
                return match.group(1).strip()

        # Fallback: search the full page text.
        text = soup.get_text(" ", strip=True)

        match = re.search(
            r"(?i)\bDeadline\s*[:：]\s*(.*?)(?=\s+Study in:|\s+Course starts\b|$)",
            text,
        )

        if match:
            return match.group(1).strip()

        return None

    def _extract_country(self, html: str) -> str | None:
        """Extract country from the explicit 'Study in' field."""

        soup = BeautifulSoup(html, "html.parser")

        text = soup.get_text(" ", strip=True)

        match = re.search(
            r"(?i)\bStudy in:\s*([A-Za-z][A-Za-z\s,]+?)(?=\s+(?:Next\s+)?course starts\b|\s+Brief description\b|$)",
            text,
        )

        if not match:
            return None

        country_text = match.group(1).strip()
        if "," in country_text:
            country_text = country_text.split(",")[-1].strip()

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
            if re.fullmatch(
                re.escape(country),
                country_text,
                re.IGNORECASE,
            ):
                return country

        return country_text

    def _extract_organization(self, html: str) -> str | None:
        """Extract organization from the explicit Host Institution section."""

        section = self._extract_labeled_section(
            html,
            [
                r"Host Institution\(s\)",
                r"Host Institution",
                r"Provided by",
                r"Offered by",
            ],
        )

        if section:
            return section.strip()

        return None
