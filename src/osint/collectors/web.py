"""Collector for sites with no usable feed: render the index page, follow its story links.

Per-source settings live in ``Source.config``:

- ``link_selector``: CSS selector for story links on the index page (default ``a[href]``)
- ``link_pattern``: regex a story URL must match, to keep out navigation and tag pages
- ``wait_for``: Crawl4AI wait condition, e.g. ``css:a.story``, for pages that build the list in JS
- ``max_new``: most new stories fetched per poll (default 20)
- ``same_domain``: only follow links on the index page's domain (default true)
- ``render_articles``: render story pages in the browser too (default false: plain HTTP)
- ``min_chars``: shortest extracted text accepted as a story (default 100)
- ``respect_robots``: honour robots.txt for this source (default: the global setting, off)

Extraction is rule-based (trafilatura), so no LLM is involved and runs are repeatable.
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit

import httpx
import trafilatura
from lxml import html as lxml_html

from osint.browser import BrowserFetcher
from osint.collectors.rss import ParsedItem
from osint.fulltext import RobotsCache, fetch_article
from osint.urls import canonicalize_url

MAX_LINKS = 200
# Shorter extracted text is a soft-404, cookie wall or "enable JavaScript" page, not a story.
MIN_ARTICLE_CHARS = 100


@dataclass
class WebResult:
    items: list[ParsedItem]
    error: str | None = None
    skipped: int = 0  # new stories we could not fetch or extract this time


def extract_links(html: str, base_url: str, cfg: dict) -> list[str]:
    """Story URLs found on the index page, in page order, deduplicated by canonical URL."""
    if not html.strip():
        return []
    tree = lxml_html.fromstring(html)
    pattern = re.compile(cfg["link_pattern"]) if cfg.get("link_pattern") else None
    base_host = urlsplit(base_url).hostname
    seen: set[str] = set()
    links: list[str] = []
    for el in tree.cssselect(cfg.get("link_selector", "a[href]")):
        href = (el.get("href") or "").strip()
        if not href or href.startswith(("#", "mailto:", "javascript:", "tel:")):
            continue
        url = urljoin(base_url, href)
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https"):
            continue
        if cfg.get("same_domain", True) and parts.hostname != base_host:
            continue
        canonical = canonicalize_url(url)
        if canonical == canonicalize_url(base_url) or canonical in seen:
            continue
        if pattern and not pattern.search(canonical):
            continue
        seen.add(canonical)
        links.append(url)
        if len(links) >= MAX_LINKS:
            break
    return links


def _published(date: str | None) -> datetime | None:
    if not date:
        return None
    try:
        parsed = datetime.fromisoformat(date)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_article(
    html: str, url: str, text: str | None = None, min_chars: int = MIN_ARTICLE_CHARS
) -> ParsedItem | None:
    """Turn an article page into an item, or None when no article text can be extracted.

    trafilatura reports publication dates at day precision when the page gives no time, so
    ``published_at`` may be midnight UTC of the right day.
    """
    text = text or trafilatura.extract(
        html, url=url, include_comments=False, include_tables=False, favor_precision=True
    )
    if not text or len(text) < min_chars:
        return None
    meta = trafilatura.extract_metadata(html, default_url=url)
    title = meta.title if meta else None
    published = _published(meta.date if meta else None)
    raw = json.dumps(
        {"url": url, "title": title, "date": meta.date if meta else None, "source": "web"},
        sort_keys=True,
    ).encode()
    return ParsedItem(
        external_id=canonicalize_url(url),
        url=url,
        title=title,
        content=text,
        published_at=published,
        raw=raw,
        page_html=html.encode(),
    )


def collect_web(
    browser: BrowserFetcher,
    client: httpx.Client,
    robots: RobotsCache,
    index_url: str,
    cfg: dict,
    known: Callable[[list[str]], set[str]],
) -> WebResult:
    respect_robots = cfg.get("respect_robots", robots.respect)
    robots = robots.with_respect(respect_robots)
    min_chars = cfg.get("min_chars", MIN_ARTICLE_CHARS)
    page = browser.render(index_url, wait_for=cfg.get("wait_for"), respect_robots=respect_robots)
    if page.error or (page.status or 200) >= 400:
        return WebResult([], error=page.error or f"HTTP {page.status}")

    links = extract_links(page.html, page.url, cfg)
    if not links:
        return WebResult([], error="no story links found on the index page")
    already = known([canonicalize_url(u) for u in links])
    fresh = [u for u in links if canonicalize_url(u) not in already][: cfg.get("max_new", 20)]

    items: list[ParsedItem] = []
    skipped = 0
    for url in fresh:
        item = None
        if cfg.get("render_articles", False):
            article = browser.render(url, respect_robots=respect_robots)
            if not article.error and article.html:
                item = parse_article(article.html, article.url, min_chars=min_chars)
        else:
            fetched = fetch_article(client, robots, url)
            if fetched is not None and fetched.text:
                item = parse_article(
                    fetched.html.decode(errors="replace"), url, fetched.text, min_chars=min_chars
                )
        if item is None:
            skipped += 1
        else:
            items.append(item)
    return WebResult(items, skipped=skipped)
