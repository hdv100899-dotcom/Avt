"""RSS/Atom collector: conditional fetch and entry normalisation."""

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

import feedparser
import httpx
from lxml import html as lxml_html

MAX_FEED_BYTES = 10 * 1024 * 1024


@dataclass
class FetchResult:
    kind: Literal["ok", "not_modified", "error"]
    body: bytes = b""
    etag: str | None = None
    last_modified: str | None = None
    error: str | None = None


@dataclass
class ParsedItem:
    external_id: str
    url: str | None
    title: str | None
    content: str | None
    published_at: datetime | None
    raw: bytes = field(repr=False, default=b"")


def fetch_feed(client: httpx.Client, url: str, cache: dict | None = None) -> FetchResult:
    """GET the feed, sending ETag/Last-Modified from the previous poll when we have them."""
    headers = {"Accept": "application/rss+xml, application/atom+xml, application/xml, */*"}
    cache = cache or {}
    if cache.get("etag"):
        headers["If-None-Match"] = cache["etag"]
    if cache.get("last_modified"):
        headers["If-Modified-Since"] = cache["last_modified"]
    try:
        resp = client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        return FetchResult("error", error=f"{type(exc).__name__}: {exc}")
    if resp.status_code == 304:
        return FetchResult(
            "not_modified", etag=cache.get("etag"), last_modified=cache.get("last_modified")
        )
    if resp.status_code >= 400:
        return FetchResult("error", error=f"HTTP {resp.status_code}")
    if len(resp.content) > MAX_FEED_BYTES:
        return FetchResult("error", error=f"feed larger than {MAX_FEED_BYTES} bytes")
    return FetchResult(
        "ok",
        body=resp.content,
        etag=resp.headers.get("etag"),
        last_modified=resp.headers.get("last-modified"),
    )


BLOCK_TAGS = {
    "p", "div", "br", "li", "ul", "ol", "blockquote", "pre", "table", "tr", "td", "section",
    "article", "h1", "h2", "h3", "h4", "h5", "h6",
}  # fmt: skip


def _to_text(markup: str | None) -> str | None:
    """Plain text of an HTML fragment, keeping words in adjacent blocks apart."""
    if not markup:
        return None
    try:
        root = lxml_html.fromstring(markup)
    except (ValueError, lxml_html.etree.ParserError):
        text = markup
    else:
        for el in root.iter():
            if isinstance(el.tag, str) and el.tag in BLOCK_TAGS:
                el.text = " " + (el.text or "")
                el.tail = " " + (el.tail or "")
        text = root.text_content()
    return re.sub(r"\s+", " ", text).strip() or None


def _published(entry) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed is None:
        return None
    return datetime(*parsed[:6], tzinfo=UTC)


def parse_feed(body: bytes) -> list[ParsedItem]:
    """Parse feed bytes. Raises ValueError when the body is not a feed at all."""
    feed = feedparser.parse(body)
    # feedparser is lenient: an HTML challenge page parses without error but has no version.
    if not feed.version:
        reason = feed.bozo_exception if feed.bozo else "no RSS or Atom root element"
        raise ValueError(f"not a valid feed: {reason}")

    items = []
    for entry in feed.entries:
        link = entry.get("link")
        title = _to_text(entry.get("title"))
        published = _published(entry)
        external_id = entry.get("id") or link
        if not external_id:
            seed = f"{title}|{published}"
            external_id = "sha1:" + hashlib.sha1(seed.encode()).hexdigest()
        body_html = None
        if entry.get("content"):
            body_html = entry["content"][0].get("value")
        body_html = body_html or entry.get("summary")
        raw = json.dumps(dict(entry), default=str, sort_keys=True).encode()
        items.append(
            ParsedItem(
                external_id=str(external_id),
                url=link,
                title=title,
                content=_to_text(body_html),
                published_at=published,
                raw=raw,
            )
        )
    return items
