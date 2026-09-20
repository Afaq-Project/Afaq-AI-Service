import logging
import re
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

# Arabic month names mapping
ARABIC_MONTHS = {
    "يناير": "January",
    "فبراير": "February",
    "مارس": "March",
    "أبريل": "April",
    "ابريل": "April",
    "مايو": "May",
    "يونيو": "June",
    "يوليو": "July",
    "أغسطس": "August",
    "اغسطس": "August",
    "سبتمبر": "September",
    "أكتوبر": "October",
    "اكتوبر": "October",
    "نوفمبر": "November",
    "ديسمبر": "December",
}

# Explicit regex patterns to locate deadline section in text
DEADLINE_PATTERNS = [
    re.compile(
        r"(?:deadline|application deadline|the deadline is|due date|closes on|close on|closing date|closes|applications close on|last date to apply|last date)[:\s]+([^\n\.,;]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:آخر موعد للتقديم|آخر موعد|اخر موعد للتسجيل|الموعد النهائي|تاريخ انتهاء التقديم|تاريخ الإغلاق)[:\s]+([^\n\.,;]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:before|by)[:\s]+([0-9]{1,2}(?:st|nd|rd|th)?\s+[A-Za-z\u0600-\u06FF]+\s+[0-9]{4})",
        re.IGNORECASE,
    ),
]

COMMON_DATE_FORMATS = [
    "%Y-%m-%d",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%Y/%m/%d",
    "%d %B %Y",
    "%d %b %Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%B %d %Y",
    "%b %d %Y",
]

MONTH_NAMES_PATTERN = re.compile(
    r"(?i)\b(january|february|march|april|may|june|july|august|september|october|november|december|"
    r"jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec|"
    r"يناير|فبراير|مارس|أبريل|ابريل|مايو|يونيو|يوليو|أغسطس|اغسطس|سبتمبر|أكتوبر|اكتوبر|نوفمبر|ديسمبر)\b"
)

YEAR_PATTERN = re.compile(r"\b(202[4-9]|203[0-9])\b")
NUMERIC_DATE_PATTERN = re.compile(
    r"\b(\d{1,2}[-/]\d{1,2}[-/]\d{4}|\d{4}[-/]\d{1,2}[-/]\d{1,2})\b"
)
ISO_DATETIME_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")


# Explicit exclusion keywords for non-exact deadlines
NON_EXACT_DEADLINE_PATTERNS = [
    re.compile(
        r"(?i)\b(rolling|ongoing|throughout the year|open year-round|مستمر|طوال العام)\b"
    ),  # Type D
    re.compile(
        r"(?i)\b(varies|varying|depends|depending on|تختلف|يعتمد على)\b"
    ),  # Type H
    re.compile(
        r"(?i)\b(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec|يناير|فبراير|مارس|أبريل|مايو|يونيو|يوليو|أغسطس|سبتمبر|أكتوبر|نوفمبر|ديسمبر)[a-z]*\s*[-–/to]+\s*(?:january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec|يناير|فبراير|مارس|أبريل|مايو|يونيو|يوليو|أغسطس|سبتمبر|أكتوبر|نوفمبر|ديسمبر)\b"
    ),  # Type F
    # Multiple slash dates (e.g., "15 Jan/25 Feb 2026", "8/11 Dec 2025", "14 Oct/8 Dec 2026")
    re.compile(
        r"(?i)\b\d{1,2}(?:st|nd|rd|th)?\s*(?:[a-z\u0600-\u06FF]*\s*)?/\s*\d{1,2}(?!\s*/\s*\d{2,4})\b"
    ),
]

MONTH_NAMES_LIST = (
    "january|february|march|april|may|june|july|august|september|october|november|december|"
    "jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec|"
    "يناير|فبراير|مارس|أبريل|ابريل|مايو|يونيو|يوليو|أغسطس|اغسطس|سبتمبر|أكتوبر|اكتوبر|نوفمبر|ديسمبر"
)

# Complete exact date patterns (must have Day + Month + Year or Month + Day + Year)
EXACT_DATE_PATTERNS = [
    # 1. Day Month Year (e.g., "1 December 2026", "28th February 2026", "15 يناير 2026")
    re.compile(
        rf"(?i)\b(\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{MONTH_NAMES_LIST})\s+\d{{4}})\b"
    ),
    # 2. Month Day, Year (e.g., "December 1, 2026", "May 7 2026", "مايو 7, 2026")
    re.compile(
        rf"(?i)\b((?:{MONTH_NAMES_LIST})\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}})\b"
    ),
    # 3. Numeric ISO or Slash/Dash with Day, Month, Year
    re.compile(
        r"\b(\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{4})\b"
    ),
]


def _normalize_arabic_dates(text: str) -> str:
    """يستبدل أسماء الأشهر العربية بالإنجليزية لتحليلها بسهولة."""
    normalized = text
    for ar, en in ARABIC_MONTHS.items():
        normalized = re.sub(rf"\b{ar}\b", en, normalized)
    return normalized


def _is_non_exact_expression(text: str) -> bool:
    """يتحقق مما إذا كان النص يحتوي على مؤشرات صريحة لمواعيد دورية، مستمرة، متغيرة، أو نطاقات زمنية."""
    for pattern in NON_EXACT_DEADLINE_PATTERNS:
        if pattern.search(text):
            return True
    return False


def _find_exact_dates_in_text(text: str) -> list[str]:
    """
    يستخرج جميع التواريخ الكاملة الصريحة (يوم + شهر + سنة) من النص.
    تتجاهل التواريخ الجزئية (شهر وسنة فقط أو سنة فقط).
    """
    found_matches: list[str] = []
    for pattern in EXACT_DATE_PATTERNS:
        for match in pattern.finditer(text):
            candidate = match.group(1).strip()
            if candidate not in found_matches:
                found_matches.append(candidate)
    return found_matches


def _parse_single_exact_date(date_str: str) -> datetime | None:
    """يحاول تحويل نص تاريخ محدد ومفرد بدقة إلى datetime بتوقيت UTC."""
    cleaned = str(date_str).strip()
    if not cleaned:
        return None

    # Strip surrounding noise tokens
    cleaned = re.sub(
        r"^(?:on|the|by|in|at|is|deadline\s*is|closes\s*on|due\s*on)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()

    # Strip trailing recurring labels if complete date exists
    cleaned = re.sub(
        r"\s*\(?\s*(?:annually|annual|yearly|سنويا|سنوي)\s*\)?\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()

    # Require explicit 4-digit year strictly in range 2024-2040
    year_match = re.search(r"\b(\d{4})\b", cleaned)
    if not year_match:
        return None
    year_val = int(year_match.group(1))
    if not (2024 <= year_val <= 2040):
        return None

    # Require explicit day (1-31)
    if not re.search(r"\b([1-9]|[12]\d|3[01])(?:st|nd|rd|th)?\b", cleaned):
        return None


    norm = _normalize_arabic_dates(cleaned)
    # Remove ordinal suffixes (1st, 2nd, 3rd, 4th, etc.)
    norm = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", norm)
    norm = re.sub(r"\s+", " ", norm).strip()


    # 1. Try explicit COMMON_DATE_FORMATS
    for fmt in COMMON_DATE_FORMATS:
        try:
            dt = datetime.strptime(norm, fmt)
            if 2024 <= dt.year <= 2040:
                return dt.replace(tzinfo=UTC)
        except ValueError:
            continue

    # 2. Try ISO format
    try:
        dt = datetime.fromisoformat(norm.replace("Z", "+00:00"))
        if 2024 <= dt.year <= 2040:
            return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
    except Exception:
        pass

    # 3. Try dateparser with strict settings requiring Day + Month
    try:
        import dateparser  # noqa: PLC0415

        dt = dateparser.parse(
            norm,
            settings={
                "PREFER_DATES_FROM": "future",
                "RETURN_AS_TIMEZONE_AWARE": True,
                "TIMEZONE": "UTC",
                "REQUIRE_PARTS": ["day", "month"],
            },
        )
        if dt is not None and 2024 <= dt.year <= 2040:
            return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
    except Exception:
        pass

    return None


def parse_date(date_str: str | None) -> datetime | None:
    """
    يحول النص الذي يحتوي على موعد نهائي محدد وصريح إلى كائن datetime موحد بتوقيت UTC.

    قواعد السلامة الصارمة:
    - يشترط تاريخاً نقطياً كاملاً (يوم + شهر + سنة).
    - يرفض المواعيد السنوية / الدورية غير المحددة بسنة (Annually/Recurring).
    - يرفض المواعيد المستمرة (Rolling/Ongoing).
    - يرفض التواريخ المشروطة أو المتغيرة (Varies/Depends).
    - يرفض المواعيد المتعددة أو الجولات المتنافسة (Multiple competing dates).
    - يرفض النطاقات الزمنية والأشهر المجردة (Ranges / Month-only).
    - يستخرج التاريخ الصريح حتى وإن كانت هناك كلمات تشويش محيطة به.
    """
    if not date_str:
        return None

    if isinstance(date_str, datetime):
        return (
            date_str.astimezone(UTC)
            if date_str.tzinfo
            else date_str.replace(tzinfo=UTC)
        )

    cleaned = str(date_str).strip()
    if not cleaned:
        return None

    # 1. Strict safety check: reject non-exact expressions
    if _is_non_exact_expression(cleaned):
        return None

    # 2. Try direct parsing first
    direct_dt = _parse_single_exact_date(cleaned)
    if direct_dt:
        return direct_dt

    # 3. Search for complete exact date substrings inside surrounding text
    exact_candidates = _find_exact_dates_in_text(cleaned)

    # If multiple distinct dates exist (e.g. "2 December 2025 or 8 January 2026")
    # or disjunctive/conjunctive connectors exist between dates, reject (Type E safety)
    if len(exact_candidates) > 1:
        return None

    if len(exact_candidates) == 1:
        # Check if surrounding text indicates disjunctive multiple dates (e.g. "or", "and")
        if re.search(r"\b(?:or|and|أو|و|إما)\b", cleaned, re.IGNORECASE) and re.search(
            r"\b(?:round|phase|stage|جولة|intake)\s*\d*\b", cleaned, re.IGNORECASE
        ):
            return None
        return _parse_single_exact_date(exact_candidates[0])

    return None


def extract_deadline_from_text(text: str | None) -> datetime | None:
    """يبحث في النص عن مؤشرات الموعد النهائي ويستخرج تاريخاً نقطياً صالحاً."""
    if not text:
        return None

    # Try explicit patterns first
    for pattern in DEADLINE_PATTERNS:
        match = pattern.search(text)
        if match:
            candidate = match.group(1).strip()
            parsed = parse_date(candidate)
            if parsed:
                return parsed

    return None
