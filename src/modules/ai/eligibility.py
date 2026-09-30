import re
from typing import Any

from .constants import NO_DATA_MARKER

ELIGIBILITY_PATTERN = re.compile(
    r"أهلي|اهلي|مؤهل|مستوفي|يحق\s*لي|بحق\s*لي|ينطبق\s*علي|"
    r"(?:هل|بقدر|فيني|أقدر|اقدر)\s+(?:أ|ا)?قدم|"
    r"شروط\s+(?:القبول|التقديم|الأهلية|الاهلية|المنحة|الفرصة)|"
    r"eligib|qualif|can\s+i\s+apply|am\s+i\s+allowed|requirements?\s+to\s+apply",
    re.IGNORECASE,
)

RELIABLE_STATUSES = {"cleaned"}


def _has_content(value: Any) -> bool:
    if isinstance(value, dict | list):
        return len(value) > 0
    if isinstance(value, str):
        return bool(value.strip())
    return False


def has_eligibility_data(opportunity: Any) -> bool:
    return _has_content(getattr(opportunity, "eligibility", None)) or _has_content(
        getattr(opportunity, "description", None)
    )


class EligibilityGuard:

    def is_eligibility_question(self, text: str) -> bool:
        return bool(ELIGIBILITY_PATTERN.search(text))

    def check_before_answer(self, message: str, opportunity: Any) -> str | None:
        if not self.is_eligibility_question(message):
            return None
        if getattr(opportunity, "status", None) not in RELIABLE_STATUSES:
            return "unverified_opportunity"
        if not has_eligibility_data(opportunity):
            return "missing_eligibility_data"
        return None

    def is_unanswerable(self, answer: str) -> bool:
        return not answer.strip() or NO_DATA_MARKER in answer
