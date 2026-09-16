from datetime import UTC, date, datetime, timedelta
from typing import Any

RETENTION_WINDOW_DAYS = 30


def _to_date(val: date | datetime | None) -> date | None:
    """Extracts the calendar date component from a date or datetime object."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    return val


def is_opportunity_active(
    deadline: date | datetime | None,
    now: date | datetime | None = None,
) -> bool:
    """Determines if an opportunity is still open/active based on its calendar date deadline.

    Business rules (Date-Only):
    - deadline > today  -> True (active)
    - deadline == today -> True (active for the entire day)
    - deadline < today  -> False (closed)
    - deadline is None  -> True (active/open)
    """
    deadline_date = _to_date(deadline)
    if deadline_date is None:
        return True

    current_date = _to_date(now) or datetime.now(UTC).date()
    return deadline_date >= current_date


def is_opportunity_closed(
    deadline: date | datetime | None,
    now: date | datetime | None = None,
) -> bool:
    """Determines if an opportunity's deadline calendar date has passed (deadline < today)."""
    deadline_date = _to_date(deadline)
    if deadline_date is None:
        return False
    return not is_opportunity_active(deadline_date, now)


def is_within_visibility_window(
    deadline: date | datetime | None,
    now: date | datetime | None = None,
    retention_days: int = RETENTION_WINDOW_DAYS,
    allow_null_deadline: bool = True,
) -> bool:
    """Evaluates whether an opportunity is within the active/30-day visibility window (Task 16).

    Business rules (Calendar Date comparison):
    - Future deadline (deadline > today): VISIBLE (Active).
    - Deadline is today (deadline == today): VISIBLE (Active).
    - Recently closed within 30 days (today - 30 days <= deadline < today): VISIBLE (Recently closed).
    - Closed older than 30 days (deadline < today - 30 days): EXCLUDED.
    - Null deadline: Handled via allow_null_deadline (defaults to True, pending business confirmation).

    This evaluation is strictly in-memory and non-mutating based on calendar dates.
    """
    deadline_date = _to_date(deadline)
    if deadline_date is None:
        return allow_null_deadline

    current_date = _to_date(now) or datetime.now(UTC).date()
    cutoff_date = current_date - timedelta(days=retention_days)

    return deadline_date >= cutoff_date


def filter_opportunities_by_lifecycle(
    opportunities: list[Any],
    now: date | datetime | None = None,
    retention_days: int = RETENTION_WINDOW_DAYS,
    allow_null_deadline: bool = True,
) -> list[Any]:
    """Filters a sequence of opportunity objects or dicts according to the 30-day visibility window.

    Leaves input collections and underlying database records completely unmutated.
    """
    visible_opportunities = []
    for opp in opportunities:
        if isinstance(opp, dict):
            deadline = opp.get("deadline")
        else:
            deadline = getattr(opp, "deadline", None)

        if is_within_visibility_window(
            deadline=deadline,
            now=now,
            retention_days=retention_days,
            allow_null_deadline=allow_null_deadline,
        ):
            visible_opportunities.append(opp)

    return visible_opportunities
