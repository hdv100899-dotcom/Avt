from datetime import UTC, datetime

import httpx

from osint.discover import detect_language, probe_feed, probe_many, summarise, to_seed_entry

NOW = datetime(2026, 11, 2, tzinfo=UTC)


def rss(titles, date="Mon, 02 Nov 2026 08:00:00 GMT", language=None, title="Example Wire") -> bytes:
    items = "".join(
        f"<item><title>{t}</title><link>https://e.example/{i}</link><guid>{i}</guid>"
        f"<pubDate>{date}</pubDate></item>"
        for i, t in enumerate(titles)
    )
    lang = f"<language>{language}</language>" if language else ""
    return (
        f'<?xml version="1.0"?><rss version="2.0"><channel><title>{title}</title>{lang}{items}'
        "</channel></rss>"
    ).encode()


def client_returning(response: httpx.Response | Exception) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(response, Exception):
            raise response
        return response

    return httpx.Client(transport=httpx.MockTransport(handler))


EN = [
    "Navy commissions a new patrol vessel after lengthy trials at sea",
    "Ministry says air defence programme remains on schedule this year",
    "Analysts question the cost of the long range missile procurement",
]


def test_usable_feed_is_ok_with_title_language_and_newest_date() -> None:
    r = probe_feed(
        client_returning(httpx.Response(200, content=rss(EN))), "https://e.example/f", NOW
    )
    assert (r.status, r.title, r.language, r.entries) == ("ok", "Example Wire", "en", 3)
    assert r.newest == datetime(2026, 11, 2, 8, tzinfo=UTC)


def test_blocked_statuses_are_recorded_not_retried() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(403)

    r = probe_feed(httpx.Client(transport=httpx.MockTransport(handler)), "https://e.example/f", NOW)
    assert (r.status, r.http) == ("blocked", 403) and len(calls) == 1
    assert (
        probe_feed(client_returning(httpx.Response(429)), "https://e.example/f").status == "blocked"
    )


def test_other_failures_are_classified() -> None:
    def probe(response):
        return probe_feed(client_returning(response), "https://e.example/f", NOW).status

    assert probe(httpx.Response(404)) == "dead"
    assert probe(httpx.ConnectTimeout("slow")) == "dead"
    assert (
        probe(httpx.Response(200, text="<html><body>Checking your browser</body></html>"))
        == "not_feed"
    )
    assert probe(httpx.Response(200, content=rss([]))) == "empty"
    old = rss(EN, date="Mon, 01 Jan 2024 08:00:00 GMT")
    assert probe(httpx.Response(200, content=old)) == "stale"


def test_declared_language_wins_and_scripts_decide_when_undeclared() -> None:
    russian = [
        "Министерство обороны сообщило о завершении учений на южном направлении",
        "Новый эсминец вышел на ходовые испытания в Балтийском море",
    ]
    assert detect_language(["whatever"], declared="en-US") == "en"
    assert detect_language(["x"], declared="zh_TW") == "zh"
    assert detect_language(russian) == "ru"  # undeclared: statistical guess
    assert detect_language(["한국 정부는 오늘 새로운 방위 계획을 발표했다"]) == "ko"
    assert detect_language(["海上自衛隊は新型護衛艦の就役を発表した"]) == "ja"
    assert (
        detect_language(["中央社即時新聞 國防部今天表示新型飛彈已完成測試"]) == "zh"
    )  # not Korean
    assert detect_language([], declared=None) is None


def test_seed_entry_shares_a_publisher_per_site() -> None:
    r = probe_feed(
        client_returning(httpx.Response(200, content=rss(EN))), "https://www.e.example/f", NOW
    )
    entry = to_seed_entry(r)
    assert entry == {
        "kind": "rss",
        "name": "Example Wire",
        "locator": "https://www.e.example/f",
        "publisher": "e.example",
        "poll_interval_s": 600,
        "language": "en",
    }


def test_probe_many_and_summary() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return {
            "/ok": httpx.Response(200, content=rss(EN)),
            "/blocked": httpx.Response(403),
        }.get(request.url.path, httpx.Response(404))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    results = probe_many(client, [f"https://e.example/{p}" for p in ("ok", "blocked", "gone")])
    assert [r.status for r in results] == ["ok", "blocked", "dead"]  # order preserved
    assert summarise(results) == {"ok": 1, "blocked": 1, "dead": 1}


def test_binary_response_is_not_a_feed() -> None:
    r = probe_feed(
        client_returning(httpx.Response(200, content=bytes(range(256)))), "https://e.example/f"
    )
    assert r.status == "not_feed"


PAGE = b"""<html><head>
<link rel="alternate" type="application/rss+xml" href="/feeds/news.xml">
<link rel="alternate" type="application/atom+xml" href="https://other.example/atom">
<link rel="alternate" type="text/html" href="/vi/">
<link rel="stylesheet" href="/s.css"></head><body>home</body></html>"""


def test_a_page_is_probed_through_the_feeds_it_advertises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/feeds/news.xml":
            return httpx.Response(200, content=rss(EN))
        if request.url.host == "other.example":
            return httpx.Response(403)
        return httpx.Response(200, content=PAGE)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    results = probe_many(client, ["https://e.example/"])
    by_url = {r.url: r for r in results}
    assert by_url["https://e.example/feeds/news.xml"].status == "ok"
    assert by_url["https://other.example/atom"].status == "blocked"
    assert "found on https://e.example/" in by_url["https://e.example/feeds/news.xml"].detail
    assert len(results) == 2  # the stylesheet and the html alternate are not feeds


def test_a_page_advertising_nothing_stays_not_feed() -> None:
    client = client_returning(httpx.Response(200, text="<html><body>hello</body></html>"))
    (result,) = probe_many(client, ["https://e.example/"])
    assert result.status == "not_feed"
