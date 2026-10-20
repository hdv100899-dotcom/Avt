"""Poll due sources concurrently and keep their schedules adapting to how often they post."""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from sqlalchemy.orm import Session, sessionmaker

from osint.collectors.rss import fetch_feed, parse_feed
from osint.config import user_agent
from osint.fulltext import RobotsCache, fetch_article
from osint.ingest import NewItem, ingest_items
from osint.models import RawItem, Source
from osint.snapshots import SnapshotStore
from osint.sources import due_sources, record_poll
from osint.urls import content_hash

log = logging.getLogger(__name__)

SUPPORTED_KINDS = ("rss",)
MIN_INTERVAL_S = 60
MAX_INTERVAL_S = 1800
# Feed bodies shorter than this are treated as teasers and the article page is fetched.
TEASER_CHARS = 400


@dataclass
class PollOutcome:
    source_id: int
    status: str  # "ok" | "not_modified" | "error"
    new_items: int = 0
    error: str | None = None


def next_interval(
    current: int,
    *,
    new_items: int,
    failed: bool,
    lo: int = MIN_INTERVAL_S,
    hi: int = MAX_INTERVAL_S,
) -> int:
    """Poll busy sources faster and quiet or failing ones slower, within [lo, hi]."""
    hi = max(hi, current)
    if failed:
        return min(current * 2, hi)
    if new_items > 0:
        return max(current // 2, lo)
    return min(int(current * 1.5), hi)


def make_client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": user_agent()}, timeout=20, follow_redirects=True)


def poll_source(
    factory: sessionmaker[Session],
    client: httpx.Client,
    robots: RobotsCache,
    store: SnapshotStore,
    source_id: int,
    now: datetime | None = None,
) -> PollOutcome:
    now = now or datetime.now(UTC)
    with factory() as session:
        source = session.get(Source, source_id)
        locator, config, interval = source.locator, dict(source.config), source.poll_interval_s

    result = fetch_feed(client, locator, config.get("http"))
    items, error = [], result.error
    if result.kind == "ok":
        try:
            items = parse_feed(result.body)
        except ValueError as exc:
            error = str(exc)
    failed = error is not None

    new_items: list[NewItem] = []
    with factory() as session, session.begin():
        source = session.get(Source, source_id)
        if not failed and items:
            new_items = ingest_items(session, source, items, store)
        if not failed:
            config["http"] = {"etag": result.etag, "last_modified": result.last_modified}
            config.pop("last_error", None)
        else:
            config["last_error"] = error
        source.config = config
        source.poll_interval_s = next_interval(
            interval,
            new_items=len(new_items),
            failed=failed,
            lo=config.get("min_interval_s", MIN_INTERVAL_S),
            hi=config.get("max_interval_s", MAX_INTERVAL_S),
        )
        newest = max((it.published_at for it in items if it.published_at), default=None)
        record_poll(session, source_id, now=now, success=not failed, newest_item_at=newest)

    if new_items and config.get("fulltext", True):
        enrich_fulltext(factory, client, robots, store, new_items)

    status = "error" if failed else result.kind
    return PollOutcome(source_id, status, len(new_items), error)


def enrich_fulltext(
    factory: sessionmaker[Session],
    client: httpx.Client,
    robots: RobotsCache,
    store: SnapshotStore,
    new_items: list[NewItem],
) -> None:
    """Fill in article text for teaser-only items. The items are already stored and visible."""
    for item in new_items:
        if not item.url or len(item.content or "") >= TEASER_CHARS:
            continue
        try:
            article = fetch_article(client, robots, item.url)
            if article is None:
                continue
            page_ref = store.put(article.html, "html")
            with factory() as session, session.begin():
                row = session.get(RawItem, item.id)
                row.page_snapshot_ref = page_ref
                if article.text and len(article.text) > len(row.content or ""):
                    row.content = article.text
                    row.content_hash = content_hash(row.title, row.content)
        except Exception:
            log.exception("full-text enrichment failed for %s", item.url)


def _record_crash(
    factory: sessionmaker[Session], source_id: int, now: datetime, error: str
) -> None:
    """Count an unexpected failure against the source so it backs off instead of hot-looping."""
    with factory() as session, session.begin():
        source = session.get(Source, source_id)
        source.config = {**source.config, "last_error": error}
        source.poll_interval_s = next_interval(source.poll_interval_s, new_items=0, failed=True)
        record_poll(session, source_id, now=now, success=False)


def run_once(
    factory: sessionmaker[Session],
    client: httpx.Client,
    store: SnapshotStore,
    *,
    workers: int = 8,
    limit: int | None = None,
    now: datetime | None = None,
) -> list[PollOutcome]:
    now = now or datetime.now(UTC)
    with factory() as session:
        ids = [s.id for s in due_sources(session, now, limit, kinds=SUPPORTED_KINDS)]
    if not ids:
        return []
    robots = RobotsCache(user_agent())

    def work(source_id: int) -> PollOutcome:
        try:
            return poll_source(factory, client, robots, store, source_id, now)
        except Exception as exc:
            log.exception("polling source %s failed", source_id)
            error = f"{type(exc).__name__}: {exc}"
            _record_crash(factory, source_id, now, error)
            return PollOutcome(source_id, "error", error=error)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(work, ids))


def run_forever(
    factory: sessionmaker[Session],
    client: httpx.Client,
    store: SnapshotStore,
    *,
    workers: int = 8,
    tick_s: float = 10,
) -> None:
    while True:
        outcomes = run_once(factory, client, store, workers=workers)
        if outcomes:
            new = sum(o.new_items for o in outcomes)
            errors = sum(o.status == "error" for o in outcomes)
            log.info("polled %d sources: %d new items, %d errors", len(outcomes), new, errors)
        time.sleep(tick_s)
