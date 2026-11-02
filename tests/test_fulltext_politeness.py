import httpx
import pytest

from osint import fulltext
from osint.config import DEFAULT_ROBOTS_TOKEN, robots_token
from osint.fulltext import MAX_CRAWL_DELAY_S, RobotsCache, fetch_article
from tests.test_runner import ARTICLE


class Clock:
    """Stands in for the time module: sleeping advances the clock instantly."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(round(seconds, 3))
        self.now += seconds


@pytest.fixture
def clock(monkeypatch) -> Clock:
    fake = Clock()
    monkeypatch.setattr(fulltext, "time", fake)
    return fake


def client_with(robots: str, requested: list[str] | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if requested is not None:
            requested.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=robots)
        return httpx.Response(200, text=ARTICLE, headers={"content-type": "text/html"})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_default_robots_token_is_the_product_name_not_the_user_agent() -> None:
    assert robots_token() == DEFAULT_ROBOTS_TOKEN == "AvtOSINT"


def test_a_rule_addressed_to_our_token_is_honoured() -> None:
    robots = "User-agent: AvtOSINT\nDisallow: /\n\nUser-agent: *\nAllow: /\n"
    client = client_with(robots)
    assert RobotsCache("AvtOSINT").allowed(client, "https://a.example/story") is False
    assert RobotsCache("SomeoneElse").allowed(client, "https://a.example/story") is True


def test_crawl_delay_spaces_requests_to_one_site(clock: Clock) -> None:
    cache = RobotsCache("AvtOSINT")
    client = client_with("User-agent: *\nCrawl-delay: 10\n")
    assert cache.allowed(client, "https://a.example/1")  # loads robots.txt

    cache.wait_turn("https://a.example/1")
    assert clock.sleeps == []  # first request goes straight away
    clock.now += 3
    cache.wait_turn("https://a.example/2")
    assert clock.sleeps == [7.0]  # only the remainder of the 10 seconds
    cache.wait_turn("https://a.example/3")
    assert clock.sleeps == [7.0, 10.0]


def test_crawl_delay_is_per_site_and_capped(clock: Clock) -> None:
    cache = RobotsCache("AvtOSINT")
    slow = client_with("User-agent: *\nCrawl-delay: 600\n")
    cache.allowed(slow, "https://slow.example/1")
    cache.allowed(client_with("User-agent: *\nAllow: /\n"), "https://free.example/1")

    cache.wait_turn("https://slow.example/1")
    cache.wait_turn("https://slow.example/2")
    cache.wait_turn("https://free.example/1")
    cache.wait_turn("https://free.example/2")
    assert clock.sleeps == [float(MAX_CRAWL_DELAY_S)]  # slow site capped; free site never waits


def test_fetch_article_waits_its_turn_between_pages(clock: Clock) -> None:
    requested: list[str] = []
    client = client_with("User-agent: *\nCrawl-delay: 10\n", requested)
    cache = RobotsCache("AvtOSINT")

    assert fetch_article(client, cache, "https://a.example/one") is not None
    assert fetch_article(client, cache, "https://a.example/two") is not None

    assert clock.sleeps == [10.0]
    assert requested.count("https://a.example/one") == requested.count("https://a.example/two") == 1
