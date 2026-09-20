from datetime import UTC, datetime

import pytest

from src.modules.scraping.services.cleaning_service import CleaningService
from src.modules.scraping.utils.date_parser import (
    extract_deadline_from_text,
    parse_date,
)


class TestExactDeadlineParserPositive:
    """Tests for extracting exact point-in-time deadlines with surrounding noise."""

    @pytest.mark.parametrize(
        ("input_text", "expected_year", "expected_month", "expected_day"),
        [
            (
                "is 1 December 2026 for courses starting in 2027. Read more »",
                2026,
                12,
                1,
            ),
            (
                "is 28 February 2026. Courses start September 2026.",
                2026,
                2,
                28,
            ),
            (
                "is 15 January 2026 for August 2026 intake.",
                2026,
                1,
                15,
            ),
            (
                "Deadline: December 1, 2026",
                2026,
                12,
                1,
            ),
            (
                "Application closes on May 7, 2026",
                2026,
                5,
                7,
            ),
            (
                "for UCL Global Masters Scholarship is May 7, 2026. The UK must encourage",
                2026,
                5,
                7,
            ),
            (
                "is 8 December 2025 for courses starting October 2026. Read more »",
                2025,
                12,
                8,
            ),
            (
                "is 1 November 2025 for courses starting September 2026. Read more »",
                2025,
                11,
                1,
            ),
            (
                "is 1 February 2025. Courses start September 2025. Read more »",
                2025,
                2,
                1,
            ),
            (
                "s: 30 June 2026 About the KAAD Scholarship Program",
                2026,
                6,
                30,
            ),
            (
                "آخر موعد للتقديم: 15 أكتوبر 2026 لجميع المتقدمين",
                2026,
                10,
                15,
            ),
            (
                "2026-10-31T23:59:59Z",
                2026,
                10,
                31,
            ),
            (
                "15/09/2026",
                2026,
                9,
                15,
            ),
        ],
    )
    def test_parse_date_positive_exact_cases(
        self,
        input_text: str,
        expected_year: int,
        expected_month: int,
        expected_day: int,
    ) -> None:
        result = parse_date(input_text)
        assert result is not None
        assert result.year == expected_year
        assert result.month == expected_month
        assert result.day == expected_day
        assert result.tzinfo == UTC


class TestExactDeadlineParserNegative:
    """Tests ensuring non-exact, recurring, rolling, range, and multi-round patterns return None."""

    @pytest.mark.parametrize(
        "non_exact_text",
        [
            "June 30, Annually",
            "1 November 2011 for Fall 2012 semester (offered annually)",
            "15 January (annual)",
            "التقديم لمنحة جامعة ستوكهولم يتم مرة واحدة سنوياً",
            "Ongoing",
            "Available throughout the year",
            "open year-round",
            "التقديم متاح على مدار العام",
            "2 December 2025 or 8 January 2026",
            "14 October 2025 (for US citizens) and 8 December 2026 (for all other)",
            "is 15 November 2024 and 1 December 1 2024",
            "either 15 January 2025 or 1 February 2025",
            "September-November 2026",
            "February-October 2026",
            "August-October 2026",
            "Deadline varies depending on the chosen course",
            "varies per country but is around September 2026",
            "depends on university admission deadline",
            "December 2026",
            "January 2027",
            "2027",
            "Fall 2027",
            "Courses starts AY 2027/2028",
            "for 2026/2027 academic year",
            "",
            None,
        ],
    )
    def test_parse_date_negative_non_exact_cases(
        self, non_exact_text: str | None
    ) -> None:
        result = parse_date(non_exact_text)
        assert result is None


class TestCleaningServiceExactDeadlineIntegration:
    """Tests integration of CleaningService with exact deadline extraction."""

    def test_clean_extracts_messy_exact_deadline(self) -> None:
        service = CleaningService()
        raw_data = {
            "title": "TU Delft Excellence Scholarships",
            "description": "Excellence scholarships for international students.",
            "deadline": "is 1 December 2026 for courses starting in 2027. Read more »",
            "source_url": "https://example.com/scholarship",
        }
        cleaned = service.clean(raw_data)
        assert isinstance(cleaned["deadline"], datetime)
        assert cleaned["deadline"].year == 2026
        assert cleaned["deadline"].month == 12
        assert cleaned["deadline"].day == 1

    def test_clean_fallback_to_description_for_unparseable_deadline(self) -> None:
        service = CleaningService()
        raw_data = {
            "title": "Geneva Excellence Fellowships",
            "description": "<p>Deadline: 28 February 2026 for all international applicants.</p>",
            "deadline": "Varies by faculty",
            "source_url": "https://example.com/scholarship",
        }
        cleaned = service.clean(raw_data)
        assert isinstance(cleaned["deadline"], datetime)
        assert cleaned["deadline"].year == 2026
        assert cleaned["deadline"].month == 2
        assert cleaned["deadline"].day == 28

    def test_clean_leaves_non_exact_deadline_as_none(self) -> None:
        service = CleaningService()
        raw_data = {
            "title": "East West Center Fellowships",
            "description": "<p>Offered annually for students across Asia.</p>",
            "deadline": "June 30, Annually",
            "source_url": "https://example.com/scholarship",
        }
        cleaned = service.clean(raw_data)
        assert cleaned["deadline"] is None

    def test_extract_deadline_from_text_direct(self) -> None:
        text = "Important update: Application deadline is 15 January 2026. Please apply early."
        dt = extract_deadline_from_text(text)
        assert dt is not None
        assert dt.year == 2026
        assert dt.month == 1
        assert dt.day == 15
