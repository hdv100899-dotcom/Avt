"""Work out when a report was published when the feed does not say it cleanly."""

import re
from datetime import UTC, datetime, timedelta, tzinfo
from email.utils import parsedate_to_datetime

from dateutil import parser as dateutil_parser

# 2019-10/21, 2026/10/31, 2026-11-02 (year-month-day with / or -), and 20261102.
URL_DATE = re.compile(
    r"(?<!\d)(20\d{2})[-/](0?[1-9]|1[0-2])[-/](0?[1-9]|[12]\d|3[01])(?!\d)"
    r"|(?<!\d)(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)"
)
FUTURE_SLACK = timedelta(days=1)


def _plausible(value: datetime, now: datetime | None) -> datetime | None:
    now = now or datetime.now(UTC)
    return value if value <= now + FUTURE_SLACK else None  # a date in the future is a mistake


def date_from_url(url: str | None, now: datetime | None = None) -> datetime | None:
    """The day a URL says the page is from (midnight UTC), or None."""
    for match in URL_DATE.finditer(url or ""):
        groups = [g for g in match.groups() if g]
        try:
            value = datetime(*(int(g) for g in groups), tzinfo=UTC)
        except ValueError:
            continue
        return _plausible(value, now)
    return None


def parse_loose_date(
    text: str | None, now: datetime | None = None, tz: tzinfo | None = None
) -> datetime | None:
    """Parse a date string of any common form (RFC 822, ISO 8601, day-first local formats).

    A date with no zone is read in ``tz`` (the source's local time), UTC when not given.
    """
    text = (text or "").replace("\u202f", " ").strip()  # narrow no-break space before AM/PM
    if not text:
        return None
    text = re.sub(r"([+-]\d{2})$", r"\g<1>00", text)  # "+07" means +0700, not seven minutes
    value: datetime | None = None
    try:
        value = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        pass
    if value is None:
        try:
            value = datetime.fromisoformat(text)  # unambiguous: year first
        except ValueError:
            pass
    if value is None:
        try:
            # A 12-hour clock marks the US style (11/2/2026 11:15 AM is 2 November); the plain
            # 02/11/2026 14:20 style is day first.
            value = dateutil_parser.parse(text, dayfirst=not re.search(r"\b[AP]\.?M\b", text, re.I))
        except (ValueError, OverflowError):
            return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=tz or UTC)
    return _plausible(value.astimezone(UTC), now)
