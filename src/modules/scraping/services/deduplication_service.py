import hashlib
import logging
import re
from typing import Any

from src.modules.core.database.repositories.opportunity_repository import (
    OpportunityRepository,
)

logger = logging.getLogger(__name__)


class DeduplicationService:
    """يقوم بحساب بصمة المحتوى content_hash وكشف الفرص المكررة بعد التوحيد."""

    def __init__(self, opportunity_repo: OpportunityRepository | None = None) -> None:
        self._repo = opportunity_repo
        self._seen_hashes: set[str] = set()
        self._seen_source_urls: set[str] = set()

    def generate_content_hash(self, data: dict[str, Any]) -> str:
        """
        يولد بصمة فريدة sha256 محصنة ضد الفروقات الشكلية (مسافات، ترقيم، حالة الأحرف).
        يتم حسابها بعد إجراء عملية الـ normalization.
        """
        title = self._normalize_for_hashing(data.get("title") or "")
        org = self._normalize_for_hashing(data.get("organization") or "")
        opp_type = self._normalize_for_hashing(data.get("opportunity_type") or "")
        country = self._normalize_for_hashing(data.get("country") or "")

        # If title is available, use normalized composite string
        if title:
            raw_signature = f"{title}|{org}|{opp_type}|{country}"
        else:
            raw_signature = self._normalize_url_for_hashing(
                data.get("source_url") or ""
            )

        return hashlib.sha256(raw_signature.encode("utf-8")).hexdigest()

    def _normalize_for_hashing(self, text: str) -> str:
        """يطبّع النص بإزالة علامات الترقيم والمسافات الزائدة وتحويله إلى lowercase."""
        if not text:
            return ""
        # Lowercase and replace punctuation with single space
        cleaned = re.sub(r"[^\w\s]", " ", text.lower())
        # Collapse multiple whitespaces
        return " ".join(cleaned.split()).strip()

    def _normalize_url_for_hashing(self, url: str) -> str:
        """يطبع الرابط بإزالة البروتوكول والشرطة المائلة في النهاية."""
        if not url:
            return ""
        u = url.strip().lower()
        u = re.sub(r"^https?://", "", u)
        u = re.sub(r"^www\.", "", u)
        return u.rstrip("/")

    async def is_duplicate(
        self, data: dict[str, Any], content_hash: str | None = None
    ) -> bool:
        """يفحص ما إذا كانت الفرصة مكررة في الدفعة الحالية أو في قاعدة البيانات."""
        h = content_hash or self.generate_content_hash(data)
        source_url = data.get("source_url") or ""
        norm_source_url = self._normalize_url_for_hashing(source_url)

        # 1. Check in-memory batch cache
        if h in self._seen_hashes:
            return True

        if norm_source_url and norm_source_url in self._seen_source_urls:
            return True

        # 2. Check in database if repository is available
        if self._repo is not None:
            try:
                # Check by content_hash (title + org + opp_type + country)
                exists_hash = await self._repo.exists_by_content_hash(h)
                if exists_hash:
                    self._seen_hashes.add(h)
                    if norm_source_url:
                        self._seen_source_urls.add(norm_source_url)
                    return True

                # Check by source_url (prevents duplicates when title changes for same detail page)
                if norm_source_url:
                    exists_url = await self._repo.exists_by_source_url(source_url)
                    if not exists_url and source_url.endswith("/"):
                        exists_url = await self._repo.exists_by_source_url(
                            source_url.rstrip("/")
                        )
                    elif not exists_url and not source_url.endswith("/"):
                        exists_url = await self._repo.exists_by_source_url(
                            source_url + "/"
                        )

                    if exists_url:
                        self._seen_hashes.add(h)
                        self._seen_source_urls.add(norm_source_url)
                        return True
            except Exception as exc:
                logger.warning("Error checking duplicate in database: %s", exc)

        return False

    def mark_as_seen(self, content_hash: str, source_url: str | None = None) -> None:
        """يسجل البصمة ورابط المصدر كفرصة تمت معالجتها في الدفعة الحالية."""
        self._seen_hashes.add(content_hash)
        if source_url:
            norm_url = self._normalize_url_for_hashing(source_url)
            if norm_url:
                self._seen_source_urls.add(norm_url)

    def reset_batch(self) -> None:
        """يمسح ذاكرة الدفعة الحالية لبدء دفعة جلب جديدة."""
        self._seen_hashes.clear()
        self._seen_source_urls.clear()
