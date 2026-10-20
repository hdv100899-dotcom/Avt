import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from osint.dedup import group_item, group_pending, item_simhash
from osint.models import EventGroup, Evidence, RawItem
from osint.simhash import MAX_DISTANCE, distance
from osint.sources import add_source
from osint.urls import canonicalize_url, content_hash

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
VOCAB = [f"word{i}" for i in range(400)]


def article(seed: int, words: int = 150) -> str:
    rng = random.Random(seed)
    return " ".join(rng.choice(VOCAB) for _ in range(words))


def make_source(session: Session, n: int):
    return add_source(session, kind="rss", locator=f"https://s{n}.example/feed", name=f"S{n}")


def add_item(
    session: Session,
    source,
    ext: str,
    *,
    content: str,
    title: str = "Headline",
    url: str | None = None,
    published: datetime | None = None,
    collected: datetime = NOW,
    group: bool = True,
):
    item = RawItem(
        source_id=source.id,
        external_id=ext,
        url=url,
        url_canonical=canonicalize_url(url) if url else None,
        title=title,
        content=content,
        published_at=published,
        collected_at=collected,
        content_hash=content_hash(title, content),
        simhash=item_simhash(title, content),
        analysis_status="pending",
    )
    session.add(item)
    session.flush()
    gid = group_item(session, item.id) if group else None
    return item, gid


def evidence(session: Session, group_id: int) -> list[tuple[int, bool]]:
    rows = session.execute(
        select(Evidence.raw_item_id, Evidence.is_origin)
        .where(Evidence.event_group_id == group_id)
        .order_by(Evidence.raw_item_id)
    )
    return [(r[0], r[1]) for r in rows]


def count_groups(session: Session, ids: set[int]) -> int:
    return session.scalar(
        select(func.count()).select_from(EventGroup).where(EventGroup.id.in_(ids))
    )


def test_unrelated_items_get_separate_groups(session: Session) -> None:
    s = make_source(session, 1)
    _, g1 = add_item(session, s, "a", content=article(1), url="https://x.example/1")
    _, g2 = add_item(session, s, "b", content=article(2), url="https://x.example/2")
    assert g1 != g2
    assert len(evidence(session, g1)) == 1 and evidence(session, g1)[0][1] is True


def test_same_canonical_url_groups_across_sources(session: Session) -> None:
    a, b = make_source(session, 1), make_source(session, 2)
    i1, g1 = add_item(session, a, "a", content=article(1), url="https://x.example/story")
    i2, g2 = add_item(
        session, b, "b", content=article(9), url="https://X.example/story/?utm_source=rss"
    )
    assert g1 == g2
    assert {e[0] for e in evidence(session, g1)} == {i1.id, i2.id}


def test_identical_body_with_different_url_groups(session: Session) -> None:
    a, b = make_source(session, 1), make_source(session, 2)
    _, g1 = add_item(session, a, "a", content=article(5), url="https://a.example/1")
    _, g2 = add_item(session, b, "b", content=article(5), url="https://b.example/other")
    assert g1 == g2


def test_near_duplicate_groups_and_heavily_rewritten_does_not(session: Session) -> None:
    a, b, c = (make_source(session, n) for n in (1, 2, 3))
    base = article(7)
    near = base + " subscribe to our newsletter for daily updates"
    assert distance(item_simhash("Headline", base), item_simhash("Headline", near)) <= MAX_DISTANCE
    rewritten = " ".join(
        w if i % 3 else "changed" for i, w in enumerate(base.split())
    )  # a third of the words differ
    _, g1 = add_item(session, a, "a", content=base, url="https://a.example/1")
    _, g2 = add_item(session, b, "b", content=near, url="https://b.example/2")
    _, g3 = add_item(session, c, "c", content=rewritten, url="https://c.example/3")
    assert g1 == g2
    assert g3 != g1


def test_short_identical_text_is_not_grouped_without_url(session: Session) -> None:
    a, b = make_source(session, 1), make_source(session, 2)
    _, g1 = add_item(session, a, "a", content="Daily briefing", url="https://a.example/1")
    _, g2 = add_item(session, b, "b", content="Daily briefing", url="https://b.example/2")
    assert g1 != g2


def test_body_match_outside_time_window_is_separate_but_url_match_is_not(session: Session) -> None:
    a, b = make_source(session, 1), make_source(session, 2)
    old = NOW - timedelta(days=10)
    _, g_old = add_item(
        session, a, "a", content=article(11), url="https://a.example/1", collected=old
    )
    _, g_new = add_item(session, b, "b", content=article(11), url="https://b.example/2")
    assert g_old != g_new
    _, g_same_url = add_item(session, b, "c", content=article(12), url="https://a.example/1")
    assert g_same_url == g_old


def test_fifteen_reposts_keep_fifteen_evidence_and_earliest_origin(session: Session) -> None:
    sources = [make_source(session, n) for n in range(15)]
    published = {n: NOW - timedelta(hours=15 - n) for n in range(15)}  # source 0 posted first
    created = {}
    order = list(range(15))
    random.Random(1).shuffle(order)  # collected in a different order from publication
    gids = set()
    for n in order:
        item, gid = add_item(
            session,
            sources[n],
            f"p{n}",
            content=article(21),
            url=f"https://s{n}.example/p",
            published=published[n],
        )
        created[n] = item.id
        gids.add(gid)
    assert len(gids) == 1
    rows = evidence(session, gids.pop())
    assert len(rows) == 15
    assert [r[0] for r in rows if r[1]] == [created[0]]  # exactly one origin, the earliest post


def test_group_takes_origin_title_and_time_span(session: Session) -> None:
    a, b = make_source(session, 1), make_source(session, 2)
    _, g = add_item(
        session,
        a,
        "a",
        title="Repost",
        content=article(31),
        published=NOW - timedelta(hours=1),
        collected=NOW,
    )
    add_item(
        session,
        b,
        "b",
        title="Original",
        content=article(31),
        published=NOW - timedelta(hours=3),
        collected=NOW + timedelta(minutes=5),
    )
    group = session.get(EventGroup, g)
    assert group.title == "Original"
    assert group.first_seen_at == NOW and group.last_seen_at == NOW + timedelta(minutes=5)


def test_item_bridging_two_groups_merges_them(session: Session) -> None:
    a, b, c = (make_source(session, n) for n in (1, 2, 3))
    i1, g1 = add_item(session, a, "a", content=article(41), url="https://a.example/1")
    i2, g2 = add_item(session, b, "b", content=article(42), url="https://b.example/2")
    assert g1 != g2
    # Same URL as the first, same body as the second.
    i3, g3 = add_item(session, c, "c", content=article(42), url="https://a.example/1")
    assert g3 == min(g1, g2)
    assert {e[0] for e in evidence(session, g3)} == {i1.id, i2.id, i3.id}
    assert sum(1 for e in evidence(session, g3) if e[1]) == 1
    assert count_groups(session, {g1, g2}) == 1


def test_lone_headline_joins_group_once_full_text_arrives(session: Session) -> None:
    a, b = make_source(session, 1), make_source(session, 2)
    _, g_full = add_item(session, a, "a", content=article(51), url="https://a.example/1")
    teaser, g_teaser = add_item(session, b, "b", content="Short teaser.", url="https://b.example/2")
    assert g_teaser != g_full

    teaser.content = article(51)
    teaser.content_hash = content_hash(teaser.title, teaser.content)
    teaser.simhash = item_simhash(teaser.title, teaser.content)
    session.flush()
    assert group_item(session, teaser.id) == g_full
    assert count_groups(session, {g_teaser}) == 0  # the emptied group is gone
    assert len(evidence(session, g_full)) == 2


def test_item_already_in_shared_group_is_not_moved(session: Session) -> None:
    a, b, c = (make_source(session, n) for n in (1, 2, 3))
    _, g1 = add_item(session, a, "a", content=article(61), url="https://a.example/1")
    i2, _ = add_item(session, b, "b", content=article(61), url="https://b.example/2")
    _, g_other = add_item(session, c, "c", content=article(62), url="https://c.example/3")
    i2.content = article(62)
    i2.content_hash = content_hash(i2.title, i2.content)
    i2.simhash = item_simhash(i2.title, i2.content)
    session.flush()
    assert group_item(session, i2.id) == g1  # stays with the story it was first grouped with
    assert group_item(session, i2.id) == g1  # and re-running changes nothing
    assert len(evidence(session, g1)) == 2 and len(evidence(session, g_other)) == 1


def test_group_item_is_idempotent(session: Session) -> None:
    s = make_source(session, 1)
    item, g = add_item(session, s, "a", content=article(71))
    assert group_item(session, item.id) == g
    assert len(evidence(session, g)) == 1


def test_group_pending_groups_only_ungrouped_items(session: Session) -> None:
    a, b = make_source(session, 1), make_source(session, 2)
    add_item(session, a, "a", content=article(81), group=False)
    add_item(session, b, "b", content=article(81), group=False)
    add_item(session, b, "c", content=article(82), group=False)
    assert group_pending(session) == 3
    assert group_pending(session) == 0
    groups = session.scalar(select(func.count(func.distinct(Evidence.event_group_id))))
    assert groups == 2
