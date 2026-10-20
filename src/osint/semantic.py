"""Group reports of the same event that share no wording, using embeddings.

Deliberately conservative. A wrong merge hides an independent report behind a repost, which is
worse than leaving two reports of one event apart. The thresholds below come from a hand-labelled
sample of 11 real same-event pairs against same-topic pairs (see docs/ARCHITECTURE.md); they are a
starting point to be re-checked as data grows.
"""

from datetime import timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from osint.dedup import _group_size, _sort_key, refresh_group
from osint.embeddings import Embedder, embedding_text
from osint.models import EventGroup, Evidence, RawItem

# The closest member of the group must be at least this similar ...
MIN_BEST = 0.75
# ... and so must the group as a whole on average, so one lucky pair cannot chain a story together.
MIN_MEAN = 0.70
# Same window as exact-duplicate matching. Syndicated copies can lag by several days (a TWZ story
# of 16 Oct reappeared in Military Times on 20 Oct); the similarity thresholds do the real work.
WINDOW = timedelta(days=7)
NEIGHBOURS = 30


def embed_pending(session: Session, embedder: Embedder, limit: int = 64) -> list[int]:
    """Embed up to ``limit`` items that have no embedding yet; return their ids, oldest first."""
    rows = session.execute(
        select(RawItem.id, RawItem.title, RawItem.content)
        .where(
            RawItem.embedding.is_(None),
            (RawItem.title.is_not(None)) | (RawItem.content.is_not(None)),
        )
        .order_by(RawItem.id)
        .limit(limit)
    ).all()
    if not rows:
        return []
    vectors = embedder.embed([embedding_text(title, content) for _, title, content in rows])
    for (item_id, _, _), vector in zip(rows, vectors, strict=True):
        session.execute(
            update(RawItem)
            .where(RawItem.id == item_id)
            .values(embedding=vector, embedding_model=embedder.model_name)
        )
    return [r[0] for r in rows]


def semantic_group_item(session: Session, item_id: int) -> int | None:
    """Join a lone item to the group of the event it reports, if one is clearly the same event.

    Returns the group joined, or None when the item stays where it is. Items already sharing a
    group are left alone, and an item never joins a group that already holds a report from its
    own source (a source's loose series, such as weekly trackers, are not one event).
    """
    item = session.get(RawItem, item_id)
    if item is None or item.embedding is None:
        return None
    existing = session.execute(
        select(Evidence.id, Evidence.event_group_id).where(Evidence.raw_item_id == item_id)
    ).first()
    own = existing[1] if existing else None
    if own is not None and _group_size(session, own) > 1:
        return None

    when = min(item.published_at or item.collected_at, item.collected_at)
    distance = RawItem.embedding.cosine_distance(item.embedding)
    neighbours = session.execute(
        select(Evidence.event_group_id, (1 - distance).label("sim"))
        .join(RawItem, RawItem.id == Evidence.raw_item_id)
        .where(
            RawItem.id != item.id,
            RawItem.embedding.is_not(None),
            _sort_key().between(when - WINDOW, when + WINDOW),
            distance <= 1 - MIN_BEST,
            *([Evidence.event_group_id != own] if own is not None else []),
        )
        .order_by(distance)
        .limit(NEIGHBOURS)
    ).all()

    best_by_group: dict[int, float] = {}
    for group_id, sim in neighbours:
        best_by_group.setdefault(group_id, float(sim))

    chosen: tuple[float, float, int] | None = None  # (mean, best, group)
    for group_id, best in best_by_group.items():
        same_source = session.scalar(
            select(func.count())
            .select_from(Evidence)
            .join(RawItem, RawItem.id == Evidence.raw_item_id)
            .where(Evidence.event_group_id == group_id, RawItem.source_id == item.source_id)
        )
        if same_source:
            continue
        mean = session.scalar(
            select(func.avg(1 - distance))
            .select_from(RawItem)
            .join(Evidence, Evidence.raw_item_id == RawItem.id)
            .where(Evidence.event_group_id == group_id, RawItem.embedding.is_not(None))
        )
        if mean is not None and mean >= MIN_MEAN and (chosen is None or (mean, best) > chosen[:2]):
            chosen = (float(mean), best, group_id)
    if chosen is None:
        return None

    _, best, target = chosen
    if own is None:
        session.add(
            Evidence(
                event_group_id=target,
                raw_item_id=item_id,
                is_origin=False,
                match_reason="semantic",
                match_score=best,
            )
        )
    else:
        session.execute(
            update(Evidence)
            .where(Evidence.id == existing[0])
            .values(
                event_group_id=target, is_origin=False, match_reason="semantic", match_score=best
            )
        )
        session.flush()
        session.execute(delete(EventGroup).where(EventGroup.id == own))
    session.flush()
    refresh_group(session, target)
    return target


def cluster_step(
    factory: sessionmaker[Session], embedder: Embedder, batch: int = 64
) -> tuple[int, int]:
    """Embed one batch of new items and group them. Returns (embedded, joined_a_group)."""
    with factory() as session, session.begin():
        ids = embed_pending(session, embedder, batch)
        joined = sum(semantic_group_item(session, i) is not None for i in ids)
    return len(ids), joined


def reconsider_singletons(session: Session) -> int:
    """Re-examine every embedded item that is alone in its group; return how many joined one.

    Use after changing the thresholds or the window, or after a model upgrade re-embedded items.
    """
    singleton_groups = (
        select(Evidence.event_group_id).group_by(Evidence.event_group_id).having(func.count() == 1)
    )
    alone = (
        select(Evidence.raw_item_id)
        .join(RawItem, RawItem.id == Evidence.raw_item_id)
        .where(RawItem.embedding.is_not(None), Evidence.event_group_id.in_(singleton_groups))
        .order_by(Evidence.raw_item_id)
    )
    return sum(semantic_group_item(session, i) is not None for i in list(session.scalars(alone)))
