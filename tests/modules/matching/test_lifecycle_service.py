from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.modules.matching.services.lifecycle_service import (
    filter_opportunities_by_lifecycle,
    is_opportunity_active,
    is_opportunity_closed,
    is_within_visibility_window,
)
from src.modules.scraping.models.cleaned_opportunity import CleanedOpportunityDTO


class TestLifecycleService:
    @pytest.fixture
    def today_date(self) -> date:
        return date(2026, 9, 15)

    @pytest.fixture
    def today_datetime(self, today_date: date) -> datetime:
        return datetime(
            today_date.year, today_date.month, today_date.day, 14, 30, 0, tzinfo=UTC
        )

    def test_deadline_tomorrow_is_active_and_visible(self, today_date: date):
        tomorrow = today_date + timedelta(days=1)
        assert is_opportunity_active(tomorrow, now=today_date) is True
        assert is_opportunity_closed(tomorrow, now=today_date) is False
        assert is_within_visibility_window(tomorrow, now=today_date) is True

    def test_deadline_today_is_active_for_entire_day(
        self, today_date: date, today_datetime: datetime
    ):
        # Both date and datetime representing today must evaluate to active
        assert is_opportunity_active(today_date, now=today_date) is True
        assert is_opportunity_closed(today_date, now=today_date) is False
        assert is_within_visibility_window(today_date, now=today_date) is True

        # Even if deadline timestamp is earlier in the same calendar day (e.g. 08:00 AM while now is 14:30 PM)
        earlier_today = datetime(2026, 9, 15, 8, 0, 0, tzinfo=UTC)
        assert is_opportunity_active(earlier_today, now=today_datetime) is True
        assert is_opportunity_closed(earlier_today, now=today_datetime) is False
        assert is_within_visibility_window(earlier_today, now=today_datetime) is True

    def test_deadline_yesterday_is_closed_but_visible(self, today_date: date):
        yesterday = today_date - timedelta(days=1)
        assert is_opportunity_active(yesterday, now=today_date) is False
        assert is_opportunity_closed(yesterday, now=today_date) is True
        assert is_within_visibility_window(yesterday, now=today_date) is True

    def test_deadline_within_30_days_is_visible(self, today_date: date):
        within_30d = today_date - timedelta(days=15)
        assert is_opportunity_active(within_30d, now=today_date) is False
        assert is_opportunity_closed(within_30d, now=today_date) is True
        assert is_within_visibility_window(within_30d, now=today_date) is True

    def test_deadline_older_than_30_days_is_excluded(self, today_date: date):
        older_than_30d = today_date - timedelta(days=31)
        assert is_opportunity_active(older_than_30d, now=today_date) is False
        assert is_opportunity_closed(older_than_30d, now=today_date) is True
        assert is_within_visibility_window(older_than_30d, now=today_date) is False

    def test_exact_30_day_calendar_boundary(self, today_date: date):
        exact_30d = today_date - timedelta(days=30)
        assert is_within_visibility_window(exact_30d, now=today_date) is True

        past_30d = today_date - timedelta(days=31)
        assert is_within_visibility_window(past_30d, now=today_date) is False

    def test_null_deadline_handling_configurable(self, today_date: date):
        assert is_opportunity_active(None, now=today_date) is True
        assert is_opportunity_closed(None, now=today_date) is False
        assert (
            is_within_visibility_window(None, now=today_date, allow_null_deadline=True)
            is True
        )
        assert (
            is_within_visibility_window(None, now=today_date, allow_null_deadline=False)
            is False
        )

    def test_filter_opportunities_preserves_order_and_excludes_expired(
        self, today_date: date
    ):
        opp_future = CleanedOpportunityDTO(
            source_id=uuid4(),
            title="Future Scholarship",
            source_url="https://example.com/1",
            deadline=datetime(2026, 9, 20, 0, 0, 0, tzinfo=UTC),
        )
        opp_today = CleanedOpportunityDTO(
            source_id=uuid4(),
            title="Closes Today",
            source_url="https://example.com/2",
            deadline=datetime(2026, 9, 15, 9, 0, 0, tzinfo=UTC),
        )
        opp_yesterday = CleanedOpportunityDTO(
            source_id=uuid4(),
            title="Closed Yesterday",
            source_url="https://example.com/3",
            deadline=datetime(2026, 9, 14, 0, 0, 0, tzinfo=UTC),
        )
        opp_35d_ago = CleanedOpportunityDTO(
            source_id=uuid4(),
            title="Closed 35 Days Ago",
            source_url="https://example.com/4",
            deadline=datetime(2026, 8, 10, 0, 0, 0, tzinfo=UTC),
        )
        opp_no_deadline = CleanedOpportunityDTO(
            source_id=uuid4(),
            title="Open Perpetual",
            source_url="https://example.com/5",
            deadline=None,
        )

        opportunities = [
            opp_future,
            opp_today,
            opp_yesterday,
            opp_35d_ago,
            opp_no_deadline,
        ]
        filtered = filter_opportunities_by_lifecycle(opportunities, now=today_date)

        assert len(filtered) == 4
        assert filtered[0].title == "Future Scholarship"
        assert filtered[1].title == "Closes Today"
        assert filtered[2].title == "Closed Yesterday"
        assert filtered[3].title == "Open Perpetual"
        assert opp_35d_ago not in filtered

    def test_filter_opportunities_supports_dicts_and_namespaces(self, today_date: date):
        raw_items = [
            {"title": "Active", "deadline": today_date + timedelta(days=2)},
            {"title": "Closed Recent", "deadline": today_date - timedelta(days=10)},
            {"title": "Closed Old", "deadline": today_date - timedelta(days=40)},
            SimpleNamespace(title="Namespace Active", deadline=today_date),
        ]

        filtered = filter_opportunities_by_lifecycle(raw_items, now=today_date)
        assert len(filtered) == 3
        assert filtered[0]["title"] == "Active"
        assert filtered[1]["title"] == "Closed Recent"
        assert filtered[2].title == "Namespace Active"

    def test_no_mutation_of_input_records(self, today_date: date):
        original_deadline = datetime(2026, 9, 10, 10, 0, 0, tzinfo=UTC)
        opp = CleanedOpportunityDTO(
            source_id=uuid4(),
            title="Original Title",
            source_url="https://example.com/test",
            status="cleaned",
            deadline=original_deadline,
        )

        _ = filter_opportunities_by_lifecycle([opp], now=today_date)

        assert opp.deadline == original_deadline
        assert opp.status == "cleaned"
        assert opp.title == "Original Title"
