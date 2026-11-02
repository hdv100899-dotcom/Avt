"""Poll due sources concurrently and keep their schedules adapting to how often they post."""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from osint.browser import BrowserFetcher, BrowserUnavailable
from osint.collectors.rss import ParsedItem, fetch_feed, parse_feed
from osint.collectors.web import collect_web
from osint.config import robots_token, user_agent
from osint.dedup import group_item, item_simhash
from osint.embeddings import Embedder
from osint.fulltext import RobotsCache, fetch_article
from osint.ingest import NewItem, ingest_items
from osint.models import RawItem, Source
from osint.semantic import cluster_step
from osint.snapshots import SnapshotStore
from osint.sources import due_sources, record_poll
from osint.urls import content_hash

log = logging.getLogger(__name__)

SUPPORTED_KINDS = ("rss", "web")
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


@dataclass
class Collected:
    """What one collection attempt produced, whatever the source kind."""

    kind: str  # "ok" | "not_modified" | "error"
    items: list[ParsedItem]
    error: str | None = None
    http: dict | None = None  # validators to send next time (feeds only)


def _collect_rss(client: httpx.Client, locator: str, config: dict) -> Collected:
    result = fetch_feed(client, locator, config.get("http"))
    items, error = [], result.error
    if result.kind == "ok":
        try:
            items = parse_feed(result.body)
        except ValueError as exc:
            error = str(exc)
    if error is not None:
        return Collected("error", [], error)
    http = {"etag": result.etag, "last_modified": result.last_modified}
    return Collected(result.kind, items, http=http)


def _collect_web(
    factory: sessionmaker[Session],
    client: httpx.Client,
    robots: RobotsCache,
    browser: BrowserFetcher | None,
    source_id: int,
    locator: str,
    config: dict,
) -> Collected:
    if browser is None:
        return Collected("error", [], "no browser fetcher configured for a web source")

    def known(urls: list[str]) -> set[str]:
        with factory() as session:
            rows = session.scalars(
                select(RawItem.external_id).where(
                    RawItem.source_id == source_id, RawItem.external_id.in_(urls)
                )
            )
            return set(rows)

    try:
        result = collect_web(browser, client, robots, locator, config, known)
    except BrowserUnavailable as exc:
        return Collected("error", [], f"browser unavailable: {exc}")
    if result.error:
        return Collected("error", [], result.error)
    if result.skipped:
        log.info("%s: %d new stories could not be fetched or read", locator, result.skipped)
    return Collected("ok", result.items)


def poll_source(
    factory: sessionmaker[Session],
    client: httpx.Client,
    robots: RobotsCache,
    store: SnapshotStore,
    source_id: int,
    now: datetime | None = None,
    browser: BrowserFetcher | None = None,
) -> PollOutcome:
    now = now or datetime.now(UTC)
    with factory() as session:
        source = session.get(Source, source_id)
        kind, locator = source.kind, source.locator
        config, interval = dict(source.config), source.poll_interval_s

    if kind == "web":
        result = _collect_web(factory, client, robots, browser, source_id, locator, config)
    else:
        result = _collect_rss(client, locator, config)
    items, error = result.items, result.error
    failed = error is not None

    new_items: list[NewItem] = []
    with factory() as session, session.begin():
        source = session.get(Source, source_id)
        if not failed and items:
            new_items = ingest_items(session, source, items, store)
        if not failed:
            if result.http is not None:
                config["http"] = result.http
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

    if new_items and kind == "rss" and config.get("fulltext", True):
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
                    row.simhash = item_simhash(row.title, row.content)
                    session.flush()
                    group_item(session, item.id)
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
    browser: BrowserFetcher | None = None,
) -> list[PollOutcome]:
    now = now or datetime.now(UTC)
    with factory() as session:
        ids = [s.id for s in due_sources(session, now, limit, kinds=SUPPORTED_KINDS)]
    if not ids:
        return []
    robots = RobotsCache(robots_token())

    def work(source_id: int) -> PollOutcome:
        try:
            return poll_source(factory, client, robots, store, source_id, now, browser)
        except Exception as exc:
            log.exception("polling source %s failed", source_id)
            error = f"{type(exc).__name__}: {exc}"
            _record_crash(factory, source_id, now, error)
            return PollOutcome(source_id, "error", error=error)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(work, ids))


# Embedding is CPU-bound; cap it per scheduler pass so polling stays responsive.
CLUSTER_BATCHES_PER_PASS = 4


def run_forever(
    factory: sessionmaker[Session],
    client: httpx.Client,
    store: SnapshotStore,
    *,
    workers: int = 8,
    tick_s: float = 10,
    embedder: Embedder | None = None,
    browser: BrowserFetcher | None = None,
) -> None:
    while True:
        outcomes = run_once(factory, client, store, workers=workers, browser=browser)
        if outcomes:
            new = sum(o.new_items for o in outcomes)
            errors = sum(o.status == "error" for o in outcomes)
            log.info("polled %d sources: %d new items, %d errors", len(outcomes), new, errors)
        if embedder is not None:
            _cluster_some(factory, embedder)
        time.sleep(tick_s)


def _cluster_some(factory: sessionmaker[Session], embedder: Embedder) -> None:
    try:
        for _ in range(CLUSTER_BATCHES_PER_PASS):
            embedded, joined = cluster_step(factory, embedder)
            if embedded:
                log.info("embedded %d items, %d joined an existing event", embedded, joined)
            if embedded == 0:
                break
    except Exception:
        # A missing model or a transient failure must not stop collection.
        log.exception("clustering pass failed; will retry on the next pass")
