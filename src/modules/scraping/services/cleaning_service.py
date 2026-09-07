import logging
import re
from typing import Any
from urllib.parse import urlparse

from ..utils.date_parser import extract_deadline_from_text, parse_date
from ..utils.text_cleaner import clean_html, clean_text, extract_urls

logger = logging.getLogger(__name__)

# Keywords that indicate an official application URL
APPLICATION_URL_KEYWORDS = [
    "apply",
    "application",
    "register",
    "scholarship",
    "form",
    "portal",
    "official",
    "link",
    "تقديم",
    "سجل",
    "استمارة",
]


def _extract_domain(url: str) -> str:
    """Extracts the netloc (domain) from a URL for comparison."""
    try:
        netloc = urlparse(url).netloc.lower()
        return re.sub(r"^www\.", "", netloc)
    except Exception:
        return ""


class CleaningService:
    """يقوم بتنظيف المحتوى النصي واستخراج الحقول المنظمة من البيانات الخام."""

    def clean(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """ينظف الحقول الأساسية المستلمة من المحول."""
        title = clean_text(clean_html(raw_data.get("title")))
        raw_description = raw_data.get("description") or raw_data.get("content") or ""
        description = clean_html(raw_description)

        organization = clean_text(clean_html(raw_data.get("organization"))) or None
        location = clean_text(clean_html(raw_data.get("location"))) or None
        country = clean_text(clean_html(raw_data.get("country"))) or None
        source_url = raw_data.get("source_url") or raw_data.get("link") or ""

        # Resolve deadline
        deadline = None
        if raw_data.get("deadline"):
            deadline = parse_date(raw_data["deadline"])
        if not deadline and description:
            deadline = extract_deadline_from_text(description)

        # Resolve application URL (do NOT default to source_url unless explicit)
        app_url = raw_data.get("application_url")
        if not app_url and raw_description:
            app_url = self._extract_application_link(str(raw_description), source_url)

        return {
            "title": title,
            "description": description,
            "organization": organization,
            "location": location,
            "country": country,
            "deadline": deadline,
            "application_url": app_url,
            "source_url": source_url,
            "opportunity_type": raw_data.get("opportunity_type"),
            "funding_type": raw_data.get("funding_type"),
            "study_levels": raw_data.get("study_levels") or [],
            "fields_of_study": raw_data.get("fields_of_study") or [],
            "is_remote": raw_data.get("is_remote", False),
            "eligibility": raw_data.get("eligibility") or {},
        }

    def _extract_application_link(
        self, html_content: str, source_url: str
    ) -> str | None:
        """يستخرج رابط التقديم الرسمي من وسوم <a> داخل النص مع تجنب الروابط الداخلية والوسائط.

        يتم تجاهل الروابط التي تنتمي لنفس النطاق كـ source_url (روابط داخلية للموقع).
        رابط التقديم الحقيقي يكون في الغالب على نطاق خارجي (جامعة، مؤسسة، بوابة).
        """
        source_domain = _extract_domain(source_url)

        # Find hrefs with surrounding text
        matches = re.findall(
            r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
            html_content,
            re.IGNORECASE | re.DOTALL,
        )
        for href, anchor_text in matches:
            href_clean = href.strip()
            href_lower = href_clean.lower()
            anchor_lower = anchor_text.lower()

            # Skip anchor links, javascript, and images/css/js
            if (
                href_clean.startswith("#")
                or href_clean.startswith("javascript:")
                or href_clean.startswith("mailto:")
            ):
                continue
            if href_clean == source_url or href_clean.rstrip("/") == source_url.rstrip(
                "/"
            ):
                continue
            if any(
                href_lower.endswith(ext)
                for ext in [
                    ".jpg",
                    ".jpeg",
                    ".png",
                    ".gif",
                    ".webp",
                    ".css",
                    ".js",
                    ".svg",
                ]
            ):
                continue

            # Skip links from the same domain as source_url (internal site links)
            href_domain = _extract_domain(href_clean)
            if source_domain and href_domain and href_domain == source_domain:
                continue

            if any(
                kw in anchor_lower or kw in href_lower
                for kw in APPLICATION_URL_KEYWORDS
            ):
                return href_clean

        # Check extracted URLs if explicit application keyword was found in URL path
        urls = extract_urls(html_content)
        for url in urls:
            url_clean = url.strip()
            url_lower = url_clean.lower()
            if url_clean != source_url and url_clean.rstrip("/") != source_url.rstrip(
                "/"
            ):
                # Skip same-domain URLs
                if source_domain and _extract_domain(url_clean) == source_domain:
                    continue
                if not any(
                    url_lower.endswith(ext)
                    for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp", ".css", ".js"]
                ):
                    if any(
                        kw in url_lower
                        for kw in [
                            "apply",
                            "application",
                            "register",
                            "portal",
                            "forms",
                        ]
                    ):
                        return url_clean

        return None
