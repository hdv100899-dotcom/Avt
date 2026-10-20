"""Group raw items into event groups.

Every raw item keeps its own evidence row. Items are joined to one group when they share a
canonical URL, an identical body, or a near-identical body (SimHash). The group's origin is
the earliest publication, so reposts are never counted as independent confirmations.
"""

from datetime import timedelta

from sqlalchemy import cast, delete, func, select, update
from sqlalchemy.dialects.postgresql import BIT
from sqlalchemy.orm import Session

from osint.models import EventGroup, Evidence, RawItem
from osint.simhash import MAX_DISTANCE, simhash

# Body-based matches only make sense for items collected near each other in time.
WINDOW = timedelta(days=7)
# Shorter bodies (headline-only items) match by URL only; boilerplate would collide.
MIN_CONTENT_CHARS = 80
SIMHASH_TEXT_CHARS = 3000


def item_simhash(title: str | None, content: str | None) -> int | None:
    return simhash(f"{title or ''} {(content or '')[:SIMHASH_TEXT_CHARS]}")


def _sort_key():
    """Publication time, never later than collection time (feeds can carry wrong dates)."""
    return func.least(
        func.coalesce(RawItem.published_at, RawItem.collected_at), RawItem.collected_at
    )


def find_candidate_groups(
    session: Session, item: RawItem, exclude_group: int | None = None
) -> dict[int, str]:
    """Groups holding an equivalent item, mapped to why ("url", "content_hash" or "simhash")."""
    base = (
        select(Evidence.event_group_id)
        .join(RawItem, RawItem.id == Evidence.raw_item_id)
        .where(RawItem.id != item.id)
    )
    if exclude_group is not None:
        base = base.where(Evidence.event_group_id != exclude_group)
    near = RawItem.collected_at.between(item.collected_at - WINDOW, item.collected_at + WINDOW)

    found: dict[int, str] = {}
    if item.url_canonical:
        for gid in session.scalars(base.where(RawItem.url_canonical == item.url_canonical)):
            found.setdefault(gid, "url")
    if item.content_hash and len(item.content or "") >= MIN_CONTENT_CHARS:
        for gid in session.scalars(base.where(RawItem.content_hash == item.content_hash, near)):
            found.setdefault(gid, "content_hash")
    if item.simhash is not None:
        differing_bits = cast(RawItem.simhash.op("#")(item.simhash), BIT(64))
        near_duplicates = base.where(
            RawItem.simhash.is_not(None), near, func.bit_count(differing_bits) <= MAX_DISTANCE
        )
        for gid in session.scalars(near_duplicates):
            found.setdefault(gid, "simhash")
    return found


def refresh_group(session: Session, group_id: int) -> None:
    """Recompute origin, title and time span of a group from its evidence."""
    rows = session.execute(
        select(Evidence.id, RawItem.id, RawItem.title, _sort_key(), RawItem.collected_at)
        .join(RawItem, RawItem.id == Evidence.raw_item_id)
        .where(Evidence.event_group_id == group_id)
    ).all()
    if not rows:
        session.execute(delete(EventGroup).where(EventGroup.id == group_id))
        return
    origin = min(rows, key=lambda r: (r[3], r[1]))
    # Clear first: at most one origin per group is enforced by a partial unique index.
    session.execute(
        update(Evidence).where(Evidence.event_group_id == group_id).values(is_origin=False)
    )
    session.execute(update(Evidence).where(Evidence.id == origin[0]).values(is_origin=True))
    session.execute(
        update(EventGroup)
        .where(EventGroup.id == group_id)
        .values(
            title=origin[2],
            first_seen_at=min(r[4] for r in rows),
            last_seen_at=max(r[4] for r in rows),
        )
    )
    session.expire_all()


def merge_groups(session: Session, keep: int, drop: int) -> None:
    session.execute(
        update(Evidence)
        .where(Evidence.event_group_id == drop)
        .values(event_group_id=keep, is_origin=False)
    )
    session.execute(delete(EventGroup).where(EventGroup.id == drop))
    session.flush()
    refresh_group(session, keep)


def _group_size(session: Session, group_id: int) -> int:
    return session.scalar(
        select(func.count()).select_from(Evidence).where(Evidence.event_group_id == group_id)
    )


def group_item(session: Session, item_id: int) -> int:
    """Put an item into the right event group (creating one if needed); return its group id.

    An item that already shares a group with others stays put. An item alone in its own group
    is re-examined, so a headline-only item can join a group once its full text arrives.
    """
    item = session.get(RawItem, item_id)
    existing = session.execute(
        select(Evidence.id, Evidence.event_group_id).where(Evidence.raw_item_id == item_id)
    ).first()
    own = existing[1] if existing else None
    if own is not None and _group_size(session, own) > 1:
        return own

    candidates = find_candidate_groups(session, item, exclude_group=own)
    if not candidates:
        if own is not None:
            return own
        group = EventGroup(title=item.title)
        session.add(group)
        session.flush()
        session.add(Evidence(event_group_id=group.id, raw_item_id=item_id, is_origin=True))
        session.flush()
        refresh_group(session, group.id)
        return group.id

    target = min(candidates)
    reason = candidates[target]
    for other in sorted(set(candidates) - {target}):
        merge_groups(session, target, other)
    if own is None:
        session.add(
            Evidence(
                event_group_id=target, raw_item_id=item_id, is_origin=False, match_reason=reason
            )
        )
    else:
        session.execute(
            update(Evidence)
            .where(Evidence.id == existing[0])
            .values(event_group_id=target, is_origin=False, match_reason=reason)
        )
        session.flush()
        session.execute(delete(EventGroup).where(EventGroup.id == own))
    session.flush()
    refresh_group(session, target)
    return target


def group_pending(session: Session, limit: int | None = None) -> int:
    """Group every item that has no evidence row yet, oldest first. Returns how many."""
    stmt = (
        select(RawItem.id)
        .outerjoin(Evidence, Evidence.raw_item_id == RawItem.id)
        .where(Evidence.id.is_(None))
        .order_by(RawItem.id)
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    ids = list(session.scalars(stmt))
    for item_id in ids:
        group_item(session, item_id)
    return len(ids)


def backfill_simhash(session: Session) -> int:
    """Compute SimHash for items stored before the column existed. Returns how many were set."""
    rows = session.execute(
        select(RawItem.id, RawItem.title, RawItem.content).where(
            RawItem.simhash.is_(None), RawItem.content.is_not(None)
        )
    ).all()
    updated = 0
    for item_id, title, content in rows:
        value = item_simhash(title, content)
        if value is not None:
            session.execute(update(RawItem).where(RawItem.id == item_id).values(simhash=value))
            updated += 1
    return updated
