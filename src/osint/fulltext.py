"""Fetch an article page and extract its main text, honouring robots.txt."""

import threading
from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx
import trafilatura

MAX_PAGE_BYTES = 5 * 1024 * 1024


class RobotsCache:
    """robots.txt per origin. Unreachable robots.txt (5xx, timeout) means do not fetch."""

    def __init__(self, user_agent: str) -> None:
        self.user_agent = user_agent
        self._parsers: dict[str, RobotFileParser | None] = {}
        self._lock = threading.Lock()

    def allowed(self, client: httpx.Client, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        with self._lock:
            if origin not in self._parsers:
                self._parsers[origin] = self._load(client, origin)
            parser = self._parsers[origin]
        return parser is not None and parser.can_fetch(self.user_agent, url)

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
