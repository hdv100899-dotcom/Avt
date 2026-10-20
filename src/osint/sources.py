"""Source registry: which sources we watch, in what state, and when each is due.

Sources found by discovery never go straight into rotation: they start as
``probation`` and only a person moves them to ``active``.
"""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from osint.models import SOURCE_KINDS, SOURCE_STATUSES, SOURCE_TIERS, Source

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "probation": {"active", "rejected"},
    "active": {"paused", "rejected"},
    "paused": {"active", "rejected"},
    "rejected": {"probation"},
}

POLLED_STATUSES = ("active", "probation")


class SourceError(ValueError):
    pass


def add_source(
    session: Session,
    *,
    kind: str,
    locator: str,
    name: str,
    tier: str = "B",
    language: str | None = None,
    status: str | None = None,
    poll_interval_s: int = 300,
    trust_score: float = 0.5,
    discovered_from_id: int | None = None,
    config: dict | None = None,
) -> Source:
    if kind not in SOURCE_KINDS:
        raise SourceError(f"unknown kind {kind!r}; expected one of {SOURCE_KINDS}")
    if tier not in SOURCE_TIERS:
        raise SourceError(f"unknown tier {tier!r}; expected one of {SOURCE_TIERS}")
    locator = locator.strip()
    if not locator:
        raise SourceError("locator must not be empty")

    if status is None:
        status = "probation" if discovered_from_id is not None else "active"
    if status not in SOURCE_STATUSES:
        raise SourceError(f"unknown status {status!r}; expected one of {SOURCE_STATUSES}")
    if discovered_from_id is not None and status != "probation":
        raise SourceError("discovered sources must start in probation")

    existing = session.scalar(select(Source).where(Source.kind == kind, Source.locator == locator))
    if existing is not None:
        raise SourceError(f"source already exists: {kind} {locator} (id={existing.id})")

    source = Source(
        kind=kind,
        locator=locator,
        name=name,
        tier=tier,
        language=language,
        status=status,
        poll_interval_s=poll_interval_s,
        trust_score=trust_score,
        discovered_from_id=discovered_from_id,
        config=config or {},
    )
    session.add(source)
    session.flush()
    return source


def set_status(session: Session, source_id: int, new_status: str) -> Source:
    source = session.get(Source, source_id)
    if source is None:
        raise SourceError(f"no source with id {source_id}")
    if new_status not in ALLOWED_TRANSITIONS.get(source.status, set()):
        raise SourceError(f"cannot move source {source_id} from {source.status} to {new_status}")
    source.status = new_status
    session.flush()
    return source


def list_sources(session: Session, status: str | None = None) -> list[Source]:
    stmt = select(Source).order_by(Source.id)
    if status is not None:
        stmt = stmt.where(Source.status == status)
    return list(session.scalars(stmt))


def due_sources(
    session: Session,
    now: datetime,
    limit: int | None = None,
    kinds: Sequence[str] | None = None,
) -> list[Source]:
    """Sources whose poll interval has elapsed, never-polled first, then longest-waiting."""
    next_due = Source.last_polled_at + func.make_interval(0, 0, 0, 0, 0, 0, Source.poll_interval_s)
    stmt = (
        select(Source)
        .where(Source.status.in_(POLLED_STATUSES))
        .where((Source.last_polled_at.is_(None)) | (next_due <= now))
        .order_by(Source.last_polled_at.asc().nulls_first(), Source.id)
    )
    if kinds is not None:
        stmt = stmt.where(Source.kind.in_(kinds))
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.scalars(stmt))


def record_poll(
    session: Session,
    source_id: int,
    *,
    now: datetime,
    success: bool,
    newest_item_at: datetime | None = None,
) -> Source:
    source = session.get(Source, source_id)
    if source is None:
        raise SourceError(f"no source with id {source_id}")
    source.last_polled_at = now
    if success:
        source.last_success_at = now
        source.consecutive_failures = 0
        if newest_item_at is not None and (
            source.last_item_at is None or newest_item_at > source.last_item_at
        ):
            source.last_item_at = newest_item_at
    else:
        source.consecutive_failures += 1
    session.flush()
    return source
