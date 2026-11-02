"""Fetch an article page and extract its main text; robots.txt is honoured when enabled."""

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
# Even with robots.txt switched off we pause between requests to one site: hammering it only gets
# our address blocked.
MIN_REQUEST_GAP_S = 1.0


class RobotsCache:
    """robots.txt per origin. Unreachable robots.txt (5xx, timeout) means do not fetch.

    With ``respect=False`` nothing is blocked and robots.txt is never fetched; requests to one
    site are still spaced by MIN_REQUEST_GAP_S.
    """

    def __init__(self, user_agent: str, respect: bool = True) -> None:
        self.user_agent = user_agent
        self.respect = respect
        self._parsers: dict[str, RobotFileParser | None] = {}
        self._lock = threading.Lock()
        self._turns: dict[str, threading.Lock] = {}
        self._last_request: dict[str, float] = {}

    def with_respect(self, respect: bool) -> "RobotsCache":
        """A view of this cache with another policy, sharing what has been learned so far."""
        if respect == self.respect:
            return self
        view = RobotsCache(self.user_agent, respect)
        view._parsers, view._lock = self._parsers, self._lock
        view._turns, view._last_request = self._turns, self._last_request
        return view

    def allowed(self, client: httpx.Client, url: str) -> bool:
        if not self.respect:
            return True
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        with self._lock:
            if origin not in self._parsers:
                self._parsers[origin] = self._load(client, origin)
            parser = self._parsers[origin]
        return parser is not None and parser.can_fetch(self.user_agent, url)

    def wait_turn(self, url: str) -> None:
        """Wait out the site's Crawl-delay (or the minimum gap) since our last request to it."""
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        with self._lock:
            parser = self._parsers.get(origin) if self.respect else None
            turn = self._turns.setdefault(origin, threading.Lock())
        delay = (parser.crawl_delay(self.user_agent) if parser else None) or 0
        delay = min(delay, MAX_CRAWL_DELAY_S) if self.respect else MIN_REQUEST_GAP_S
        if not delay:
            return
        with turn:  # concurrent threads queue up behind one another
            wait = self._last_request.get(origin, 0) + delay - time.monotonic()
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
