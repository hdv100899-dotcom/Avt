"""Probe candidate feed URLs and sort them into usable, blocked and broken.

A source that refuses our requests (403, 429, ...) is recorded as blocked and left alone: this
tool never retries with a disguised client.
"""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urljoin, urlsplit

import feedparser
import httpx
from langdetect import DetectorFactory, LangDetectException, detect
from lxml import html as lxml_html

DetectorFactory.seed = 0  # make language detection repeatable

BLOCKED_STATUSES = {401, 403, 429, 451}
SAMPLE_TITLES = 12
MAX_FEED_BYTES = 10 * 1024 * 1024


@dataclass
class ProbeResult:
    url: str
    status: str  # ok | blocked | not_feed | dead | empty | stale
    http: int | None = None
    title: str | None = None
    language: str | None = None
    entries: int = 0
    newest: datetime | None = None
    detail: str | None = None


def _script_language(text: str) -> str | None:
    """Language implied by the writing system, for scripts where statistics are unreliable."""
    hangul = sum("\uac00" <= c <= "\ud7a3" for c in text)
    kana = sum("\u3040" <= c <= "\u30ff" for c in text)
    han = sum("\u4e00" <= c <= "\u9fff" for c in text)
    letters = sum(c.isalpha() for c in text) or 1
    if hangul / letters > 0.2:
        return "ko"
    if kana / letters > 0.1:
        return "ja"
    if han / letters > 0.3:
        return "zh"
    return None


def detect_language(titles: list[str], declared: str | None = None) -> str | None:
    """Language of a feed. What the feed declares wins (normalised to its primary subtag);
    otherwise the writing system decides for Korean, Japanese and Chinese, and a statistical
    guess from the headlines covers the rest."""
    if declared:
        primary = declared.split("-")[0].split("_")[0].lower()
        if primary.isalpha() and 2 <= len(primary) <= 3:
            return primary
    sample = " ".join(t for t in titles if t)[:2000]
    if script := _script_language(sample):
        return script
    try:
        if len(sample) >= 40:
            return detect(sample).split("-")[0]
    except LangDetectException:
        pass
    return None


def probe_feed(
    client: httpx.Client, url: str, now: datetime | None = None, max_age_days: int = 45
) -> ProbeResult:
    now = now or datetime.now(UTC)
    try:
        resp = client.get(url)
    except httpx.HTTPError as exc:
        return ProbeResult(url, "dead", detail=f"{type(exc).__name__}: {exc}"[:200])
    if resp.status_code in BLOCKED_STATUSES:
        return ProbeResult(url, "blocked", resp.status_code, detail=f"HTTP {resp.status_code}")
    if resp.status_code >= 400:
        return ProbeResult(url, "dead", resp.status_code, detail=f"HTTP {resp.status_code}")
    if len(resp.content) > MAX_FEED_BYTES:
        return ProbeResult(url, "dead", resp.status_code, detail="feed larger than 10 MB")

    feed = feedparser.parse(resp.content)
    if not feed.get("version"):
        return ProbeResult(url, "not_feed", resp.status_code, detail="no RSS or Atom root element")

    dates = [
        datetime(*parsed[:6], tzinfo=UTC)
        for parsed in (e.get("published_parsed") or e.get("updated_parsed") for e in feed.entries)
        if parsed
    ]
    newest = max(dates, default=None)
    titles = [e.get("title", "") for e in feed.entries[:SAMPLE_TITLES]]
    result = ProbeResult(
        url,
        "ok",
        resp.status_code,
        title=" ".join((feed.feed.get("title") or "").split()) or None,
        language=detect_language(titles, feed.feed.get("language")),
        entries=len(feed.entries),
        newest=newest,
    )
    if not feed.entries:
        result.status = "empty"
    elif newest is not None and now - newest > timedelta(days=max_age_days):
        result.status, result.detail = "stale", f"newest item {newest:%Y-%m-%d}"
    return result


def probe_many(
    client: httpx.Client, urls: list[str], workers: int = 12, max_age_days: int = 45
) -> list[ProbeResult]:
    with ThreadPoolExecutor(max_workers=workers) as pool:
        batches = pool.map(lambda u: probe_with_autodiscovery(client, u, max_age_days), urls)
        return [result for batch in batches for result in batch]


def summarise(results: list[ProbeResult]) -> dict[str, int]:
    return dict(Counter(r.status for r in results))


def autodiscover_links(client: httpx.Client, page_url: str, limit: int = 5) -> list[str]:
    """Feed URLs a page advertises (<link rel="alternate" type="application/rss+xml">)."""
    try:
        resp = client.get(page_url)
        if resp.status_code >= 400:
            return []
        tree = lxml_html.fromstring(resp.content)
    except (httpx.HTTPError, ValueError, lxml_html.etree.ParserError):
        return []
    found: list[str] = []
    for link in tree.cssselect("link[rel='alternate']"):
        kind = (link.get("type") or "").lower()
        href = link.get("href")
        if href and ("rss" in kind or "atom" in kind):
            url = urljoin(str(resp.url), href)
            if url not in found:
                found.append(url)
    return found[:limit]


def probe_with_autodiscovery(
    client: httpx.Client, url: str, max_age_days: int = 45
) -> list[ProbeResult]:
    """Probe a URL; if it is a page rather than a feed, probe the feeds it advertises instead."""
    first = probe_feed(client, url, max_age_days=max_age_days)
    if first.status != "not_feed":
        return [first]
    advertised = [u for u in autodiscover_links(client, url) if u != url]
    results = [probe_feed(client, u, max_age_days=max_age_days) for u in advertised]
    for r in results:
        r.detail = f"found on {url}" + (f"; {r.detail}" if r.detail else "")
    return results or [first]


def to_seed_entry(result: ProbeResult, interval_s: int = 600) -> dict:
    """A source-seed record for a usable feed. Feeds of one site share a publisher."""
    host = (urlsplit(result.url).hostname or "").removeprefix("www.")
    entry = {
        "kind": "rss",
        "name": result.title or host,
        "locator": result.url,
        "publisher": host,
        "poll_interval_s": interval_s,
    }
    if result.language:
        entry["language"] = result.language
    return entry
