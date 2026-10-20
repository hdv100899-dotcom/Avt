from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from osint.fulltext import RobotsCache
from osint.models import Evidence, RawItem, Source
from osint.runner import next_interval, poll_source, run_once
from osint.snapshots import SnapshotStore
from osint.sources import add_source

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
SENTENCES = [
    "The ministry confirmed that new air defence units were moved to the northern region.",
    "Officials said the deployment follows a series of exercises held earlier this month.",
    "Satellite imagery published on Monday shows additional vehicles at the staging area.",
    "Analysts noted that the systems have a reported range well beyond previous deployments.",
    "A spokesperson declined to comment on the number of launchers involved in the move.",
    "Neighbouring governments have asked for clarification about the purpose of the build-up.",
    "The announcement came a day after talks on arms control stalled in the capital.",
    "Further details are expected during a briefing scheduled for later this week.",
]
ARTICLE = (
    "<html><head><title>Story</title></head><body><nav>Home | World</nav><article>"
    + "".join(f"<p>{s}</p>" for s in SENTENCES)
    + "</article><footer>Subscribe to our newsletter</footer></body></html>"
)
SYNDICATED = [
    "Shipbuilders reported record orders for escort vessels during the latest quarter.",
    "The navy plans to commission the first hull of the new class within two years.",
    "Engineers described delays in sourcing propulsion components from overseas suppliers.",
    "A parliamentary committee will review the programme budget before the end of the year.",
    "Industry groups welcomed the decision but warned about shortages of skilled welders.",
    "Training schedules for the first crews have been adjusted to match the new timeline.",
]
LONG_BODY = " ".join(SYNDICATED * 3)


def feed_xml(*guids: str, link_host: str = "articles.example", body: str | None = None) -> bytes:
    items = ""
    for g in guids:
        text = body or (LONG_BODY if g == "long" else "Short teaser.")
        items += (
            f"<item><title>Story {g}</title><link>https://{link_host}/a/{g}</link>"
            f"<guid>{g}</guid><pubDate>Mon, 20 Oct 2026 11:00:00 GMT</pubDate>"
            f"<description>{text}</description></item>"
        )
    head = '<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>'
    return f"{head}{items}</channel></rss>".encode()


class Site:
    """Fake web: one feed host and one article host, recording every request."""

    def __init__(self) -> None:
        self.feed = feed_xml("teaser", "long")
        self.etag = '"v1"'
        self.feed_status: int | None = None
        self.feed_exception: Exception | None = None
        self.feed2 = feed_xml("long", link_host="mirror.example")
        self.robots = "User-agent: *\nAllow: /\n"
        self.requested: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requested.append(url)
        if request.url.host == "feed2.example":
            return httpx.Response(200, content=self.feed2)
        if request.url.host == "feed.example":
            if self.feed_exception:
                raise self.feed_exception
            if self.feed_status:
                return httpx.Response(self.feed_status)
            if request.headers.get("if-none-match") == self.etag:
                return httpx.Response(304)
            return httpx.Response(200, content=self.feed, headers={"ETag": self.etag})
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=self.robots)
        if request.url.path.startswith("/a/"):
            return httpx.Response(200, text=ARTICLE, headers={"content-type": "text/html"})
        return httpx.Response(404)


@pytest.fixture
def site() -> Site:
    return Site()


@pytest.fixture
def env(site: Site, tmp_path: Path):
    client = httpx.Client(transport=httpx.MockTransport(site))
    return client, RobotsCache("test-agent"), SnapshotStore(tmp_path)


def make_source(factory: sessionmaker[Session], **kwargs) -> int:
    with factory() as session, session.begin():
        return add_source(
            session,
            kind="rss",
            locator="https://feed.example/rss",
            name="Feed",
            language="en",
            **kwargs,
        ).id


def load_source(factory, source_id: int) -> Source:
    with factory() as session:
        return session.get(Source, source_id)


def items(factory) -> dict[str, RawItem]:
    with factory() as session:
        return {i.external_id: i for i in session.scalars(select(RawItem))}


def test_next_interval_adapts_within_bounds() -> None:
    assert next_interval(300, new_items=3, failed=False) == 150
    assert next_interval(80, new_items=3, failed=False) == 60  # floor
    assert next_interval(300, new_items=0, failed=False) == 450
    assert next_interval(1700, new_items=0, failed=False) == 1800  # ceiling
    assert next_interval(300, new_items=0, failed=True) == 600
    assert next_interval(1500, new_items=0, failed=True) == 1800
    # An interval the operator set above the ceiling is never forced down.
    assert next_interval(3600, new_items=0, failed=False) == 3600


def test_first_poll_stores_items_snapshots_and_validators(factory, env, site) -> None:
    client, robots, store = env
    sid = make_source(factory)

    outcome = poll_source(factory, client, robots, store, sid, NOW)

    assert (outcome.status, outcome.new_items, outcome.error) == ("ok", 2, None)
    stored = items(factory)
    assert set(stored) == {"teaser", "long"}
    teaser = stored["teaser"]
    assert teaser.language == "en"
    assert teaser.url_canonical == "https://articles.example/a/teaser"
    assert b"Story teaser" in store.get(teaser.snapshot_ref)
    assert teaser.analysis_status == "pending"

    source = load_source(factory, sid)
    assert source.config["http"]["etag"] == '"v1"'
    assert source.last_polled_at == NOW and source.last_success_at == NOW
    assert source.last_item_at == datetime(2026, 10, 20, 11, 0, tzinfo=UTC)
    assert source.poll_interval_s == 150  # new items: poll faster


def test_second_poll_uses_validators_and_slows_down(factory, env, site) -> None:
    client, robots, store = env
    sid = make_source(factory)
    poll_source(factory, client, robots, store, sid, NOW)

    outcome = poll_source(factory, client, robots, store, sid, NOW + timedelta(minutes=5))

    assert (outcome.status, outcome.new_items) == ("not_modified", 0)
    assert load_source(factory, sid).poll_interval_s == 225
    assert len(items(factory)) == 2


def test_reposted_feed_without_validators_creates_no_duplicates(factory, env, site) -> None:
    client, robots, store = env
    sid = make_source(factory)
    poll_source(factory, client, robots, store, sid, NOW)
    site.etag = '"v2"'  # server ignores our validator and resends everything

    outcome = poll_source(factory, client, robots, store, sid, NOW + timedelta(minutes=5))

    assert (outcome.status, outcome.new_items) == ("ok", 0)
    assert len(items(factory)) == 2


def test_only_new_entries_are_inserted(factory, env, site) -> None:
    client, robots, store = env
    sid = make_source(factory)
    poll_source(factory, client, robots, store, sid, NOW)
    site.feed, site.etag = feed_xml("teaser", "long", "fresh"), '"v2"'

    outcome = poll_source(factory, client, robots, store, sid, NOW + timedelta(minutes=5))

    assert outcome.new_items == 1
    assert set(items(factory)) == {"teaser", "long", "fresh"}


def test_teaser_gets_full_text_and_page_snapshot(factory, env, site) -> None:
    client, robots, store = env
    sid = make_source(factory)
    poll_source(factory, client, robots, store, sid, NOW)

    stored = items(factory)
    teaser, long = stored["teaser"], stored["long"]
    assert "air defence units" in teaser.content
    assert "Subscribe to our newsletter" not in teaser.content
    assert b"<article>" in store.get(teaser.page_snapshot_ref)
    # The feed already carried the full text, so the page was not fetched.
    assert long.page_snapshot_ref is None
    assert "https://articles.example/a/long" not in site.requested


def test_robots_disallow_keeps_teaser_and_skips_page(factory, env, site) -> None:
    client, robots, store = env
    site.robots = "User-agent: *\nDisallow: /a/\n"
    sid = make_source(factory)

    poll_source(factory, client, robots, store, sid, NOW)

    teaser = items(factory)["teaser"]
    assert teaser.content == "Short teaser."
    assert teaser.page_snapshot_ref is None
    assert "https://articles.example/a/teaser" not in site.requested


def test_fulltext_can_be_disabled_per_source(factory, env, site) -> None:
    client, robots, store = env
    sid = make_source(factory, config={"fulltext": False})

    poll_source(factory, client, robots, store, sid, NOW)

    assert items(factory)["teaser"].content == "Short teaser."
    assert not any("/a/" in u for u in site.requested)


def test_http_error_is_recorded_and_backs_off(factory, env, site) -> None:
    client, robots, store = env
    site.feed_status = 503
    sid = make_source(factory)

    outcome = poll_source(factory, client, robots, store, sid, NOW)

    assert (outcome.status, outcome.error) == ("error", "HTTP 503")
    source = load_source(factory, sid)
    assert source.consecutive_failures == 1
    assert source.poll_interval_s == 600
    assert source.config["last_error"] == "HTTP 503"
    assert source.last_success_at is None and source.last_polled_at == NOW

    # Recovery clears the error and resets the failure count.
    site.feed_status = None
    poll_source(factory, client, robots, store, sid, NOW + timedelta(minutes=10))
    source = load_source(factory, sid)
    assert source.consecutive_failures == 0 and "last_error" not in source.config


def test_html_page_instead_of_feed_counts_as_failure(factory, env, site) -> None:
    client, robots, store = env
    site.feed = b"<html><body>Checking your browser before accessing the site</body></html>"
    sid = make_source(factory)

    outcome = poll_source(factory, client, robots, store, sid, NOW)

    assert outcome.status == "error" and "not a valid feed" in outcome.error
    assert load_source(factory, sid).consecutive_failures == 1
    assert items(factory) == {}


def test_run_once_polls_due_rss_sources_only(factory, env, site) -> None:
    client, _, store = env
    due = make_source(factory)
    with factory() as session, session.begin():
        add_source(session, kind="telegram", locator="@somechannel", name="TG")
        add_source(
            session, kind="rss", locator="https://feed.example/paused", name="P", status="paused"
        )

    outcomes = run_once(factory, client, store, now=NOW)

    assert [o.source_id for o in outcomes] == [due]
    assert run_once(factory, client, store, now=NOW) == []  # nothing is due again yet


def test_unexpected_crash_backs_off_instead_of_hot_looping(factory, env, site) -> None:
    client, _, store = env
    site.feed_exception = RuntimeError("parser exploded")
    sid = make_source(factory)

    (outcome,) = run_once(factory, client, store, now=NOW)

    assert outcome.status == "error" and "RuntimeError" in outcome.error
    source = load_source(factory, sid)
    assert source.consecutive_failures == 1 and source.poll_interval_s == 600
    assert run_once(factory, client, store, now=NOW + timedelta(seconds=30)) == []


def test_item_count_matches_after_repeated_runs(factory, env, site) -> None:
    client, robots, store = env
    sid = make_source(factory)
    for minute in range(3):
        poll_source(factory, client, robots, store, sid, NOW + timedelta(minutes=minute))
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(RawItem)) == 2


def test_same_story_from_two_feeds_is_one_group_with_both_evidence(factory, env, site) -> None:
    client, robots, store = env
    first = make_source(factory)
    with factory() as session, session.begin():
        second = add_source(
            session, kind="rss", locator="https://feed2.example/rss", name="Mirror", language="en"
        ).id
    poll_source(factory, client, robots, store, first, NOW)
    poll_source(factory, client, robots, store, second, NOW)

    with factory() as session:
        rows = session.execute(
            select(
                Evidence.event_group_id, RawItem.external_id, RawItem.source_id, Evidence.is_origin
            ).join(RawItem, RawItem.id == Evidence.raw_item_id)
        ).all()
    by_group: dict[int, list] = {}
    for gid, ext, src, origin in rows:
        by_group.setdefault(gid, []).append((ext, src, origin))
    sizes = sorted(len(v) for v in by_group.values())
    assert sizes == [1, 2]  # "teaser" alone; "long" from both feeds together
    (pair,) = [v for v in by_group.values() if len(v) == 2]
    assert {src for _, src, _ in pair} == {first, second}
    assert sum(1 for _, _, origin in pair if origin) == 1


def test_enriched_teaser_is_regrouped_with_story_it_matches(factory, env, site) -> None:
    client, robots, store = env
    first = make_source(factory)
    with factory() as session, session.begin():
        second = add_source(
            session, kind="rss", locator="https://feed2.example/rss", name="Mirror", language="en"
        ).id
    # The mirror already carries the full text that the teaser's article page will yield.
    site.feed2 = feed_xml("teaser", link_host="mirror.example", body=" ".join(SENTENCES))
    poll_source(factory, client, robots, store, second, NOW)

    poll_source(factory, client, robots, store, first, NOW)  # teaser stored, then enriched

    with factory() as session:
        rows = session.execute(
            select(Evidence.event_group_id, RawItem.source_id, RawItem.external_id).join(
                RawItem, RawItem.id == Evidence.raw_item_id
            )
        ).all()
    groups: dict[int, set] = {}
    for gid, src, ext in rows:
        groups.setdefault(gid, set()).add((src, ext))
    assert {(first, "teaser"), (second, "teaser")} in groups.values()
    assert {(first, "long")} in groups.values()
    assert len(groups) == 2
