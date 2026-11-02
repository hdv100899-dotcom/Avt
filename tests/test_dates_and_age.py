from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from osint.collectors.rss import parse_feed
from osint.dates import date_from_url, parse_loose_date
from osint.dedup import (
    backfill_published_from_entries,
    backfill_published_from_urls,
    prune_old_items,
)
from osint.fulltext import RobotsCache
from osint.models import EventGroup, Evidence, RawItem
from osint.runner import poll_source
from osint.snapshots import SnapshotStore
from osint.sources import add_source
from tests.test_dedup import add_item, article, make_source
from tests.test_runner import NOW, Site, items
from tests.test_runner import make_source as make_feed

CLOCK = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


@pytest.fixture
def site() -> Site:
    return Site()


@pytest.fixture
def env(site: Site, tmp_path):
    client = httpx.Client(transport=httpx.MockTransport(site))
    return client, RobotsCache("test-agent"), SnapshotStore(tmp_path)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "http://www.xinhuanet.com/mil/2019-10/21/c_1125133675.htm",
            datetime(2019, 10, 21, tzinfo=UTC),
        ),
        ("https://site.example/news/2026/10/31/story-title", datetime(2026, 10, 31, tzinfo=UTC)),
        ("https://site.example/2026-11-02/story", datetime(2026, 11, 2, tzinfo=UTC)),
        ("https://site.example/photos/20261030_gallery.html", datetime(2026, 10, 30, tzinfo=UTC)),
        (
            "https://www.oryxspioenkop.com/2023/06/silent-solidarity.html",
            None,
        ),  # year and month only
        ("https://site.example/articles/1285302.html", None),
        ("https://site.example/2026/13/45/x", None),  # not a calendar date
        ("https://site.example/2031/01/01/x", None),  # in the future
        (None, None),
    ],
)
def test_date_from_url(url, expected) -> None:
    assert date_from_url(url, CLOCK) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Mon, 02 Nov 2026 08:30:00 GMT", datetime(2026, 11, 2, 8, 30, tzinfo=UTC)),
        ("Mon, 02 Nov 2026 15:30:00 +0700", datetime(2026, 11, 2, 8, 30, tzinfo=UTC)),
        ("2026-11-02T08:30:00Z", datetime(2026, 11, 2, 8, 30, tzinfo=UTC)),
        (
            "02/11/2026 14:20",
            datetime(2026, 11, 2, 14, 20, tzinfo=UTC),
        ),  # day first, as in Vietnamese feeds
        (
            "11/2/2026 11:15:00 AM",
            datetime(2026, 11, 2, 11, 15, tzinfo=UTC),
        ),  # US style: month first
        ("11/1/2026 12:20:00\u202fPM", datetime(2026, 11, 1, 12, 20, tzinfo=UTC)),
        ("Mon, 02 Nov 2026 07:49:00 +07", datetime(2026, 11, 2, 0, 49, tzinfo=UTC)),
        ("not a date", None),
        ("", None),
        ("2031-01-01", None),
    ],
)
def test_parse_loose_date(text, expected) -> None:
    assert parse_loose_date(text, CLOCK) == expected


def test_feed_entry_dates_fall_back_to_loose_text_then_the_url() -> None:
    xml = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
    <item><title>a</title><guid>a</guid><link>https://x.example/a</link>
      <pubDate>02/11/2026 14:20</pubDate></item>
    <item><title>b</title><guid>b</guid><link>http://www.xinhuanet.com/mil/2019-10/21/c_1.htm</link></item>
    <item><title>c</title><guid>c</guid><link>https://x.example/no-date-here</link></item>
    </channel></rss>"""
    a, b, c = parse_feed(xml)
    assert a.published_at == datetime(2026, 11, 2, 14, 20, tzinfo=UTC)
    assert b.published_at == datetime(2019, 10, 21, tzinfo=UTC)
    assert c.published_at is None


def old_and_new_feed(old_days: int) -> bytes:
    def pub(days: int) -> str:
        return (NOW - timedelta(days=days)).strftime("%a, %d %b %Y %H:%M:%S GMT")

    return (
        '<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>'
        f"<item><title>Fresh</title><guid>fresh</guid><link>https://a.example/fresh</link><pubDate>{pub(1)}</pubDate>"
        "<description>" + "word " * 120 + "</description></item>"
        f"<item><title>Back catalogue</title><guid>old</guid><link>https://a.example/old</link><pubDate>{pub(old_days)}</pubDate>"
        "<description>" + "other " * 120 + "</description></item>"
        "<item><title>Undated</title><guid>und</guid><link>https://a.example/und</link>"
        "<description>" + "third " * 120 + "</description></item>"
        "</channel></rss>"
    ).encode()


def test_poll_skips_reports_older_than_the_limit_but_keeps_undated(
    factory, env, site: Site
) -> None:
    client, robots, store = env
    site.feed = old_and_new_feed(old_days=400)
    sid = make_feed(factory)

    outcome = poll_source(factory, client, robots, store, sid, NOW)

    assert (outcome.new_items, outcome.skipped_old) == (2, 1)
    assert set(items(factory)) == {"fresh", "und"}


def test_the_age_limit_can_be_changed_per_source_and_by_environment(
    factory, env, site: Site, monkeypatch
) -> None:
    client, robots, store = env
    site.feed = old_and_new_feed(old_days=10)
    wide = make_feed(factory, config={"max_age_days": 30, "fulltext": False})
    narrow = make_feed_second(factory)  # no override: the environment's limit applies
    monkeypatch.setenv("OSINT_MAX_ITEM_AGE_DAYS", "3")

    poll_source(factory, client, robots, store, wide, NOW)
    site.etag = '"v2"'
    poll_source(factory, client, robots, store, narrow, NOW)

    with factory() as session:
        titles = {
            sid: {
                r.external_id
                for r in session.scalars(select(RawItem).where(RawItem.source_id == sid))
            }
            for sid in (wide, narrow)
        }
    assert "old" in titles[wide]  # a 10-day-old report is inside this source's 30-day limit
    assert (
        "old" not in titles[narrow] and "fresh" in titles[narrow]
    )  # but outside the 3-day default


def make_feed_second(factory) -> int:
    with factory() as session, session.begin():
        return add_source(
            session,
            kind="rss",
            locator="https://feed.example/rss?x=2",
            name="Feed 2",
            config={"fulltext": False},
        ).id


def test_stale_feed_still_records_its_newest_item_date(factory, env, site: Site) -> None:
    client, robots, store = env
    site.feed = old_and_new_feed(old_days=400).replace(b"Fresh", b"Fresh")
    sid = make_feed(factory)
    from osint.models import Source

    poll_source(factory, client, robots, store, sid, NOW)
    with factory() as session:
        # last_item_at comes from everything parsed, so a dead feed shows as stale, not as healthy
        assert session.get(Source, sid).last_item_at == (NOW - timedelta(days=1)).replace(
            microsecond=0
        )


def test_prune_removes_old_reports_and_repairs_groups(session: Session) -> None:
    a, b = make_source(session, 1), make_source(session, 2)
    now = datetime.now(UTC)
    # Backfill: published long ago, collected yesterday, so it groups with yesterday's repost.
    old_origin, g = add_item(
        session,
        a,
        "old",
        content=article(1),
        published=now - timedelta(days=40),
        collected=now - timedelta(days=1),
    )
    repost, _ = add_item(
        session,
        b,
        "repost",
        content=article(1),
        published=now - timedelta(days=1),
        collected=now - timedelta(days=1),
    )
    lone_old, g_lone = add_item(
        session,
        a,
        "lone",
        content=article(2),
        published=now - timedelta(days=90),
        collected=now - timedelta(days=90),
    )
    undated, _ = add_item(session, b, "undated", content=article(3))
    assert g == session.scalar(
        select(Evidence.event_group_id).where(Evidence.raw_item_id == repost.id)
    )
    cutoff = now - timedelta(days=7)

    assert prune_old_items(session, cutoff, dry_run=True) == (2, 2)
    assert (
        session.scalar(select(func.count()).select_from(RawItem)) == 4
    )  # a dry run changes nothing

    assert prune_old_items(session, cutoff) == (2, 2)
    remaining = {r.external_id for r in session.scalars(select(RawItem))}
    assert remaining == {"repost", "undated"}
    assert session.get(EventGroup, g_lone) is None  # the group that only held an old report is gone
    survivor = session.scalar(select(Evidence).where(Evidence.raw_item_id == repost.id))
    assert survivor.is_origin  # the repost became the origin of its group
    assert prune_old_items(session, cutoff) == (0, 0)


def test_backfill_dates_undated_reports_from_their_urls(session: Session) -> None:
    src = make_source(session, 1)
    dated, _ = add_item(
        session, src, "x", content=article(1), url="http://www.xinhuanet.com/mil/2019-10/21/c_1.htm"
    )
    plain, _ = add_item(
        session, src, "y", content=article(2), url="https://x.example/story-without-date"
    )
    assert dated.published_at is None and plain.published_at is None

    assert backfill_published_from_urls(session) == 1
    session.refresh(dated)
    assert dated.published_at == datetime(2019, 10, 21, tzinfo=UTC)
    assert plain.published_at is None


def test_backfill_dates_from_the_saved_feed_entry(session: Session, tmp_path) -> None:
    import json

    store = SnapshotStore(tmp_path)
    src = make_source(session, 1)
    item, _ = add_item(session, src, "x", content=article(1))
    item.snapshot_ref = store.put(
        json.dumps({"published": "11/2/2026 11:15:00 AM"}).encode(), "json"
    )
    other, _ = add_item(session, src, "y", content=article(2))
    other.snapshot_ref = store.put(json.dumps({"title": "no date here"}).encode(), "json")
    session.flush()

    assert backfill_published_from_entries(session, store) == 1
    session.refresh(item)
    assert item.published_at == datetime(2026, 11, 2, 11, 15, tzinfo=UTC)


def test_a_date_without_a_zone_is_read_in_the_sources_local_time() -> None:
    from zoneinfo import ZoneInfo

    hcm = ZoneInfo("Asia/Ho_Chi_Minh")
    assert parse_loose_date("11/2/2026 11:15:00 AM", CLOCK, hcm) == datetime(
        2026, 11, 2, 4, 15, tzinfo=UTC
    )
    assert parse_loose_date("11/2/2026 11:15:00 AM", CLOCK) == datetime(
        2026, 11, 2, 11, 15, tzinfo=UTC
    )
    # A date that states its own zone ignores the source's.
    assert parse_loose_date("2026-11-02T08:30:00Z", CLOCK, hcm) == datetime(
        2026, 11, 2, 8, 30, tzinfo=UTC
    )


def test_poll_reads_naive_feed_dates_in_the_configured_timezone(factory, env, site: Site) -> None:
    client, robots, store = env
    site.feed = (
        b'<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>'
        b"<item><title>Local</title><guid>l</guid><link>https://a.example/l</link>"
        b"<pubDate>20/10/2026 18:00</pubDate>"
        b"<description>" + b"word " * 120 + b"</description></item></channel></rss>"
    )
    sid = make_feed(factory, config={"timezone": "Asia/Ho_Chi_Minh", "fulltext": False})
    poll_source(factory, client, robots, store, sid, NOW)
    assert items(factory)["l"].published_at == datetime(2026, 10, 20, 11, 0, tzinfo=UTC)

    bad = make_feed_second(factory)
    from osint.models import Source

    with factory() as session, session.begin():
        session.get(Source, bad).config = {"timezone": "Not/AZone", "fulltext": False}
    poll_source(
        factory, client, robots, store, bad, NOW
    )  # an unknown zone falls back to UTC, no crash
