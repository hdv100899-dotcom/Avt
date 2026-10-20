from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from osint.sources import (
    SourceError,
    add_source,
    due_sources,
    list_sources,
    record_poll,
    set_status,
)

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


def _rss(session: Session, n: int, **kwargs):
    return add_source(
        session, kind="rss", locator=f"https://example.org/{n}.xml", name=f"S{n}", **kwargs
    )


def test_manual_source_is_active_by_default(session: Session) -> None:
    assert _rss(session, 1).status == "active"


def test_discovered_source_starts_in_probation(session: Session) -> None:
    parent = _rss(session, 1)
    child = _rss(session, 2, discovered_from_id=parent.id)
    assert child.status == "probation"
    assert child.discovered_from_id == parent.id


def test_discovered_source_cannot_skip_probation(session: Session) -> None:
    parent = _rss(session, 1)
    with pytest.raises(SourceError, match="probation"):
        _rss(session, 2, discovered_from_id=parent.id, status="active")


def test_duplicate_source_rejected(session: Session) -> None:
    _rss(session, 1)
    with pytest.raises(SourceError, match="already exists"):
        _rss(session, 1)


def test_invalid_kind_and_tier_rejected(session: Session) -> None:
    with pytest.raises(SourceError, match="kind"):
        add_source(session, kind="fax", locator="x", name="x")
    with pytest.raises(SourceError, match="tier"):
        add_source(session, kind="rss", locator="x", name="x", tier="Z")


def test_status_transitions(session: Session) -> None:
    src = _rss(session, 1, status="probation")
    assert set_status(session, src.id, "active").status == "active"
    assert set_status(session, src.id, "paused").status == "paused"
    assert set_status(session, src.id, "rejected").status == "rejected"
    with pytest.raises(SourceError, match="cannot move"):
        set_status(session, src.id, "active")
    assert set_status(session, src.id, "probation").status == "probation"


def test_active_cannot_go_back_to_probation(session: Session) -> None:
    src = _rss(session, 1)
    with pytest.raises(SourceError, match="cannot move"):
        set_status(session, src.id, "probation")


def test_list_sources_filters_by_status(session: Session) -> None:
    a = _rss(session, 1)
    b = _rss(session, 2, status="paused")
    assert [s.id for s in list_sources(session, "paused")] == [b.id]
    assert {s.id for s in list_sources(session)} >= {a.id, b.id}


def test_due_sources_respects_interval_and_status(session: Session) -> None:
    never = _rss(session, 1, poll_interval_s=60)
    stale = _rss(session, 2, poll_interval_s=60)
    fresh = _rss(session, 3, poll_interval_s=60)
    paused = _rss(session, 4, status="paused")
    probation = _rss(session, 5, status="probation")
    rejected = _rss(session, 6, status="probation")
    set_status(session, rejected.id, "rejected")

    record_poll(session, stale.id, now=NOW - timedelta(seconds=61), success=True)
    record_poll(session, fresh.id, now=NOW - timedelta(seconds=59), success=True)

    due = [s.id for s in due_sources(session, NOW)]
    assert never.id in due and stale.id in due and probation.id in due
    assert fresh.id not in due and paused.id not in due and rejected.id not in due
    # Never-polled sources come first.
    assert due.index(never.id) < due.index(stale.id)


def test_due_sources_limit(session: Session) -> None:
    for n in range(5):
        _rss(session, n)
    assert len(due_sources(session, NOW, limit=2)) == 2


def test_record_poll_success_and_failure(session: Session) -> None:
    src = _rss(session, 1)
    newest = NOW - timedelta(minutes=3)

    record_poll(session, src.id, now=NOW, success=False)
    record_poll(session, src.id, now=NOW, success=False)
    assert src.consecutive_failures == 2
    assert src.last_success_at is None

    record_poll(session, src.id, now=NOW, success=True, newest_item_at=newest)
    assert src.consecutive_failures == 0
    assert src.last_success_at == NOW
    assert src.last_item_at == newest

    # An older item never moves last_item_at backwards.
    record_poll(session, src.id, now=NOW, success=True, newest_item_at=newest - timedelta(hours=1))
    assert src.last_item_at == newest


def test_record_poll_unknown_source(session: Session) -> None:
    with pytest.raises(SourceError, match="no source"):
        record_poll(session, 999_999, now=NOW, success=True)
