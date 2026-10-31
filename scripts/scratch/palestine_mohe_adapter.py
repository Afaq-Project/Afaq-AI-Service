"""
Palestinian Ministry of Education and Higher Education
Scholarship Adapter.

Source:
https://www.mohe.pna.ps/scholarships/

This adapter extracts SCHOLARSHIPS ONLY.
It does not classify internships, fellowships, or volunteering.
"""

import html
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from src.modules.scraping.adapters.base_adapter import BaseAdapter
from src.modules.infrastructure.http.base_http_client import BaseHttpClient
from src.modules.scraping.adapters.wordpress_api_adapter import WordPressApiAdapter


logger = logging.getLogger(__name__)


class PalestineMoHEAdapter(WordPressApiAdapter):
    """Adapter for scholarships published by the Palestinian MoHE."""

    DEFAULT_BASE_URL = "https://www.mohe.pna.ps"
    SCHOLARSHIPS_PATH = "/scholarships/"

    def __init__(
        self,
        source_id: str,
        source_name: str = "palestine_mohe",
        base_url: str = DEFAULT_BASE_URL,
        http_client: Optional[BaseHttpClient] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            source_id=source_id,
            source_name=source_name,
            base_url=base_url,
            http_client=http_client,
            config=config,
        )

    # ==============================================================
    # FETCH
    # ==============================================================

    async def fetch(
        self,
        limit: int = 5,
        page: int = 1,
    ) -> List[Dict[str, Any]]:
        """
        Fetch scholarship posts from the Ministry scholarship archive.
        """

        url = urljoin(
            self.base_url,
            self.SCHOLARSHIPS_PATH,
        )

        if page > 1:
            url = f"{url}?Page={page}"

        response = await self.http_client.get(url)

        response.raise_for_status()

        html_content = response.text

        soup = BeautifulSoup(
            html_content,
            "html.parser",
        )

        posts = self._extract_listing_posts(
            soup=soup,
            limit=limit,
        )

        logger.info(
            "[PalestineMoHEAdapter] Fetched %d scholarship posts.",
            len(posts),
        )

        return posts

    # ==============================================================
    # LISTING EXTRACTION
    # ==============================================================

    def _extract_listing_posts(
        self,
        soup: BeautifulSoup,
        limit: int,
    ) -> List[Dict[str, Any]]:

        results: List[Dict[str, Any]] = []

        # The archive contains article links under the scholarship section.
        # We intentionally collect links whose URL belongs to /scholarships/.
        seen_links = set()

        for link_tag in soup.find_all("a", href=True):

            href = link_tag.get("href", "").strip()

            if not href:
                continue

            absolute_url = urljoin(
                self.base_url,
                href,
            )

            # Keep only actual scholarship article pages.
            if "/scholarships/post/" not in absolute_url.lower():
                continue

            if absolute_url in seen_links:
                continue

            title = self._clean_text(
                link_tag.get_text(" ", strip=True)
            )

            if not title:
                continue

            # Ignore generic navigation links.
            if title in {
                "المنح",
                "قراءة المزيد",
                "الرئيسية",
            }:
                continue

            seen_links.add(absolute_url)

            results.append(
                {
                    "id": self._extract_post_id(
                        absolute_url
                    ),
                    "title": title,
                    "link": absolute_url,
                }
            )

            if len(results) >= limit:
                break

        return results

    # ==============================================================
    # PARSE
    # ==============================================================

    def parse(
        self,
        raw_data: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Normalize scholarship records.

        Category is ALWAYS scholarship because this adapter reads
        only from the Ministry scholarship section.
        """

        parsed_opportunities: List[Dict[str, Any]] = []

        for post in raw_data:

            if not isinstance(post, dict):
                continue

            title = self._clean_text(
                post.get("title", "")
            )

            link = post.get("link", "")

            if not title or not link:
                continue

            parsed_opportunities.append(
                {
                    "source_id": self.source_id,
                    "source_name": self.source_name,

                    # IMPORTANT:
                    # No keyword classification.
                    "category": "scholarship",
                    "opportunity_type": "scholarship",

                    "raw_post_id": post.get("id"),

                    "title": title,
                    "title_raw": title,

                    "description": post.get(
                        "description",
                        "",
                    ),

                    "link": link,

                    "application_link": post.get(
                        "application_link"
                    ),

                    "country": post.get(
                        "country"
                    ),

                    "degree_level": post.get(
                        "degree_level"
                    ),

                    "field_of_study": post.get(
                        "field_of_study"
                    ),

                    "funding_type": post.get(
                        "funding_type"
                    ),

                    "deadline": post.get(
                        "deadline"
                    ),

                    "deadline_date": post.get(
                        "deadline_date"
                    ),

                    "published_at": post.get(
                        "published_at",
                        "",
                    ),
                }
            )

        logger.info(
            "[PalestineMoHEAdapter] Parsed %d scholarships.",
            len(parsed_opportunities),
        )

        return parsed_opportunities

    # ==============================================================
    # DETAIL PAGE
    # ==============================================================

    async def enrich(
        self,
        opportunities: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Visit each official Ministry scholarship page and extract
        application link + metadata from the announcement.
        """

        enriched: List[Dict[str, Any]] = []

        for opportunity in opportunities:

            link = opportunity.get("link")

            if not link:
                enriched.append(opportunity)
                continue

            try:
                response = await self.http_client.get(link)
                response.raise_for_status()

                soup = BeautifulSoup(
                    response.text,
                    "html.parser",
                )

                detail = self._parse_detail_page(
                    soup=soup,
                    page_url=link,
                )

                opportunity.update(detail)

            except Exception as exc:
                logger.warning(
                    "[PalestineMoHEAdapter] "
                    "Failed to enrich %s: %s",
                    link,
                    exc,
                )

            enriched.append(opportunity)

        return enriched

    # ==============================================================
    # DETAIL PARSER
    # ==============================================================

    def _parse_detail_page(
        self,
        soup: BeautifulSoup,
        page_url: str,
    ) -> Dict[str, Any]:

        text = self._clean_text(
            soup.get_text(" ", strip=True)
        )

        application_link = self._extract_application_link(
            soup=soup,
            page_url=page_url,
        )

        deadline = self._extract_deadline(text)

        degree_level = self._extract_degree(text)

        country = self._extract_country(text)

        funding_type = self._extract_funding(text)

        field_of_study = self._extract_field(text)

        description = self._extract_description(
            soup
        )

        published_at = self._extract_published_date(
            soup
        )

        return {
            "description": description,
            "application_link": application_link,
            "deadline": deadline,
            "deadline_date": self._normalize_date(
                deadline
            ),
            "degree_level": degree_level,
            "country": country,
            "funding_type": funding_type,
            "field_of_study": field_of_study,
            "published_at": published_at,
        }

    # ==============================================================
    # APPLICATION LINK
    # ==============================================================

    def _extract_application_link(
        self,
        soup: BeautifulSoup,
        page_url: str,
    ) -> Optional[str]:

        candidates = []

        for a in soup.find_all("a", href=True):

            href = a.get("href", "").strip()

            if not href:
                continue

            absolute_url = urljoin(
                page_url,
                href,
            )

            text = self._clean_text(
                a.get_text(" ", strip=True)
            ).lower()

            candidates.append(
                (
                    text,
                    absolute_url,
                )
            )

        # Prefer links whose text indicates application.
        application_keywords = [
            "التقديم",
            "تقديم الطلب",
            "طلب",
            "رابط التقديم",
            "التسجيل",
            "apply",
            "application",
            "register",
            "admission",
        ]

        for text, url in candidates:

            if any(
                keyword in text
                for keyword in application_keywords
            ):
                return url

        # If no explicit application text exists,
        # prefer external links.
        for _, url in candidates:

            if (
                url.startswith("http")
                and "mohe.pna.ps" not in url.lower()
            ):
                return url

        return None

    # ==============================================================
    # METADATA EXTRACTION
    # ==============================================================

    @staticmethod
    def _extract_deadline(
        text: str,
    ) -> Optional[str]:

        patterns = [
            r"آخر موعد[^.]{0,100}",
            r"اخر موعد[^.]{0,100}",
            r"الموعد النهائي[^.]{0,100}",
            r"آخر موعد لتقديم الطلبات[^.]{0,100}",
        ]

        for pattern in patterns:

            match = re.search(
                pattern,
                text,
                re.IGNORECASE,
            )

            if match:
                return match.group(0).strip()

        return None

    @staticmethod
    def _extract_degree(
        text: str,
    ) -> Optional[str]:

        degrees = [
            ("دكتوراه", "phd"),
            ("الدكتوراه", "phd"),
            ("ماجستير", "master"),
            ("الماجستير", "master"),
            ("بكالوريوس", "bachelor"),
            ("البكالوريوس", "bachelor"),
            ("دبلوم", "diploma"),
        ]

        for keyword, value in degrees:

            if keyword in text:
                return value

        return None

    @staticmethod
    def _extract_country(
        text: str,
    ) -> Optional[str]:

        countries = [
            "الهند",
            "رومانيا",
            "تركيا",
            "تونس",
            "المغرب",
            "الجزائر",
            "بولندا",
            "باكستان",
            "الأردن",
            "عمان",
            "مصر",
            "كوبا",
            "تايلند",
            "فيتنام",
            "ماليزيا",
            "الصين",
            "اليابان",
            "ألمانيا",
            "فرنسا",
            "إيطاليا",
            "بريطانيا",
            "روسيا",
            "كوريا",
            "كازاخستان",
        ]

        for country in countries:

            if country in text:
                return country

        return None

    @staticmethod
    def _extract_funding(
        text: str,
    ) -> Optional[str]:

        if (
            "ممولة بالكامل" in text
            or "ممول بالكامل" in text
            or "تمويل كامل" in text
        ):
            return "fully_funded"

        if (
            "ممولة جزئيا" in text
            or "ممولة جزئيًا" in text
            or "تمويل جزئي" in text
        ):
            return "partially_funded"

        if (
            "غير ممولة" in text
            or "بدون تمويل" in text
        ):
            return "unfunded"

        return None

    @staticmethod
    def _extract_field(
        text: str,
    ) -> Optional[str]:

        patterns = [
            r"في مجال (.{3,100})",
            r"في تخصص (.{3,100})",
            r"تخصصات (.{3,100})",
        ]

        for pattern in patterns:

            match = re.search(
                pattern,
                text,
            )

            if match:
                return match.group(1).strip()

        return None

    @staticmethod
    def _extract_description(
        soup: BeautifulSoup,
    ) -> str:

        # Prefer article/main content.
        candidates = [
            soup.find("article"),
            soup.find("main"),
        ]

        for container in candidates:

            if container:

                text = PalestineMoHEAdapter._clean_text(
                    container.get_text(
                        " ",
                        strip=True,
                    )
                )

                if len(text) > 100:
                    return text[:2000]

        text = PalestineMoHEAdapter._clean_text(
            soup.get_text(
                " ",
                strip=True,
            )
        )

        return text[:2000]

    @staticmethod
    def _extract_published_date(
        soup: BeautifulSoup,
    ) -> str:

        text = soup.get_text(
            " ",
            strip=True,
        )

        # Examples:
        # 17 Mar 2026
        # 27 Aug 2026
        match = re.search(
            r"\b\d{1,2}\s+"
            r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
            r"\s+\d{4}\b",
            text,
            re.IGNORECASE,
        )

        if match:
            return match.group(0)

        return ""

    # ==============================================================
    # HELPERS
    # ==============================================================

    @staticmethod
    def _clean_text(
        value: Any,
    ) -> str:

        if value is None:
            return ""

        value = html.unescape(
            str(value)
        )

        value = re.sub(
            r"\s+",
            " ",
            value,
        )

        return value.strip()

    @staticmethod
    def _extract_post_id(
        url: str,
    ) -> Optional[int]:

        match = re.search(
            r"/Post/(\d+)",
            url,
            re.IGNORECASE,
        )

        if match:
            return int(match.group(1))

        return None

    @staticmethod
    def _normalize_date(
        value: Optional[str],
    ) -> Optional[str]:

        if not value:
            return None

        # Arabic date formats can be added later once we inspect
        # real Ministry announcements.
        return value