"""Fetch an article page and extract its main text, honouring robots.txt."""

import threading
import time
from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx
import trafilatura

MAX_PAGE_BYTES = 5 * 1024 * 1024
# A site's Crawl-delay is honoured up to this many seconds; longer asks are treated as this.
MAX_CRAWL_DELAY_S = 30


class RobotsCache:
    """robots.txt per origin. Unreachable robots.txt (5xx, timeout) means do not fetch."""

    def __init__(self, user_agent: str) -> None:
        self.user_agent = user_agent
        self._parsers: dict[str, RobotFileParser | None] = {}
        self._lock = threading.Lock()
        self._turns: dict[str, threading.Lock] = {}
        self._last_request: dict[str, float] = {}

    def allowed(self, client: httpx.Client, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        with self._lock:
            if origin not in self._parsers:
                self._parsers[origin] = self._load(client, origin)
            parser = self._parsers[origin]
        return parser is not None and parser.can_fetch(self.user_agent, url)

    def wait_turn(self, url: str) -> None:
        """Block until the site's Crawl-delay (if any) has passed since our last request to it."""
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        with self._lock:
            parser = self._parsers.get(origin)
            turn = self._turns.setdefault(origin, threading.Lock())
        delay = (parser.crawl_delay(self.user_agent) if parser else None) or 0
        if not delay:
            return
        with turn:  # concurrent threads queue up behind one another
            wait = (
                self._last_request.get(origin, 0) + min(delay, MAX_CRAWL_DELAY_S) - time.monotonic()
            )
            if wait > 0:
                time.sleep(wait)
            self._last_request[origin] = time.monotonic()

    def _load(self, client: httpx.Client, origin: str) -> RobotFileParser | None:
        parser = RobotFileParser()
        try:
            resp = client.get(f"{origin}/robots.txt")
        except httpx.HTTPError:
            return None
        if resp.status_code >= 500:
            return None
        if resp.status_code >= 400:
            parser.parse([])  # no robots.txt: everything allowed
        else:
            parser.parse(resp.text.splitlines())
        return parser


@dataclass
class Article:
    html: bytes
    text: str | None


def fetch_article(client: httpx.Client, robots: RobotsCache, url: str) -> Article | None:
    """Return the page and its extracted text, or None when disallowed or unreachable."""
    if not robots.allowed(client, url):
        return None
    robots.wait_turn(url)
    try:
        resp = client.get(url)
    except httpx.HTTPError:
        return None
    if resp.status_code >= 400 or len(resp.content) > MAX_PAGE_BYTES:
        return None
    text = trafilatura.extract(
        resp.text, url=url, include_comments=False, include_tables=False, favor_precision=True
    )
    return Article(html=resp.content, text=text)
