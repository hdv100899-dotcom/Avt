import os
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from osint.browser import BrowserFetcher, BrowserUnavailable, RenderedPage
from osint.collectors.web import collect_web, extract_links, parse_article
from osint.fulltext import RobotsCache
from osint.models import RawItem, Source
from osint.runner import poll_source
from osint.snapshots import SnapshotStore
from osint.sources import add_source
from tests.test_runner import SENTENCES

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
INDEX = "https://wire.example/news/"


def story(title: str, date: str | None = "2026-11-02T08:30:00Z") -> str:
    meta = f'<meta property="article:published_time" content="{date}">' if date else ""
    body = "".join(f"<p>{s}</p>" for s in SENTENCES)
    return (
        f"<html><head><title>{title}</title>{meta}</head><body><nav>Home</nav>"
        f"<article><h1>{title}</h1>{body}</article><footer>Subscribe</footer></body></html>"
    )


INDEX_HTML = """<html><body>
<a href="#top">top</a><a href="mailto:a@b.c">mail</a>
<a class="story" href="/news/2026/a1">One</a>
<a class="story" href="/news/2026/a2/?utm_source=x">Two</a>
<a class="story" href="/news/2026/a2">Two again</a>
<a class="story" href="https://other.example/news/2026/zz">Elsewhere</a>
<a class="tag" href="/tag/navy">Navy</a>
<a class="story" href="/news/">index itself</a>
</body></html>"""


class FakeBrowser:
    def __init__(self, pages: dict[str, RenderedPage]) -> None:
        self.pages = pages
        self.calls: list[tuple] = []

    def render(self, url, *, wait_for=None, respect_robots=True):
        self.calls.append((url, wait_for, respect_robots))
        return self.pages.get(url) or RenderedPage(url, 404, "", "HTTP 404")


def ok(url: str, html: str) -> RenderedPage:
    return RenderedPage(url, 200, html)


def test_extract_links_selector_pattern_domain_and_dedupe() -> None:
    cfg = {"link_selector": "a.story", "link_pattern": r"/news/\d{4}/"}
    assert extract_links(INDEX_HTML, INDEX, cfg) == [
        "https://wire.example/news/2026/a1",
        "https://wire.example/news/2026/a2/?utm_source=x",
    ]


def test_extract_links_defaults_skip_non_http_and_can_cross_domains() -> None:
    links = extract_links(INDEX_HTML, INDEX, {})
    assert not any(u.startswith("mailto:") or u.endswith("#top") for u in links)
    assert "https://other.example/news/2026/zz" not in links
    allowed = extract_links(INDEX_HTML, INDEX, {"same_domain": False})
    assert "https://other.example/news/2026/zz" in allowed
    assert extract_links("", INDEX, {}) == []


def test_parse_article_extracts_text_title_date_and_keeps_page() -> None:
    item = parse_article(story("Navy commissions vessel"), "https://wire.example/news/2026/a1")
    assert item.title == "Navy commissions vessel"
    assert "air defence units" in item.content and "Subscribe" not in item.content
    assert item.published_at == datetime(2026, 11, 2, tzinfo=UTC)  # day precision
    assert item.external_id == "https://wire.example/news/2026/a1"
    assert b"<article>" in item.page_html


def test_parse_article_without_text_or_date() -> None:
    assert parse_article("<html><body><nav>x</nav></body></html>", "https://a.example/x") is None
    assert parse_article(story("Undated", date=None), "https://a.example/y").published_at is None


def test_short_pages_are_not_stories_unless_the_source_allows() -> None:
    soft_404 = (
        "<html><body><article><p>Please enable JavaScript to continue.</p></article></body></html>"
    )
    assert parse_article(soft_404, "https://a.example/z") is None
    assert parse_article(soft_404, "https://a.example/z", min_chars=10) is not None


def mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def site_handler(requested: list[str], robots: str = "User-agent: *\nAllow: /\n"):
    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=robots)
        if request.url.path.startswith("/news/2026/"):
            return httpx.Response(200, text=story(f"Story {request.url.path[-2:]}"))
        return httpx.Response(404)

    return handler


CFG = {"link_selector": "a.story", "link_pattern": r"/news/\d{4}/"}


def run_collect(browser, client, cfg=CFG, known=lambda urls: set()):
    return collect_web(browser, client, RobotsCache("t"), INDEX, cfg, known)


def test_collect_fetches_each_new_story_over_plain_http() -> None:
    requested: list[str] = []
    browser = FakeBrowser({INDEX: ok(INDEX, INDEX_HTML)})

    result = run_collect(browser, mock_client(site_handler(requested)))

    assert result.error is None and len(result.items) == 2
    assert [c[0] for c in browser.calls] == [INDEX]  # only the index needed the browser
    assert browser.calls[0][2] is True  # robots honoured by default
    assert {i.external_id for i in result.items} == {
        "https://wire.example/news/2026/a1",
        "https://wire.example/news/2026/a2",
    }


def test_known_stories_are_not_fetched_again_and_max_new_caps_the_batch() -> None:
    requested: list[str] = []
    browser = FakeBrowser({INDEX: ok(INDEX, INDEX_HTML)})
    client = mock_client(site_handler(requested))

    seen = {"https://wire.example/news/2026/a1"}
    result = run_collect(browser, client, known=lambda urls: seen & set(urls))
    assert [i.external_id for i in result.items] == ["https://wire.example/news/2026/a2"]
    assert not any(u.endswith("/a1") for u in requested)

    capped = run_collect(browser, client, cfg={**CFG, "max_new": 1})
    assert len(capped.items) == 1


def test_robots_disallow_skips_stories_unless_source_opts_out() -> None:
    requested: list[str] = []
    robots = "User-agent: *\nDisallow: /news/2026/\n"
    browser = FakeBrowser({INDEX: ok(INDEX, INDEX_HTML)})
    client = mock_client(site_handler(requested, robots))

    blocked = run_collect(browser, client)
    assert blocked.items == [] and blocked.skipped == 2
    assert not any("/news/2026/" in u for u in requested)

    opted_out = run_collect(browser, client, cfg={**CFG, "respect_robots": False})
    assert len(opted_out.items) == 2
    assert browser.calls[-1][2] is False  # passed through to the browser's own robots check


def test_render_articles_uses_the_browser_for_story_pages() -> None:
    pages = {
        INDEX: ok(INDEX, INDEX_HTML),
        "https://wire.example/news/2026/a1": ok(
            "https://wire.example/news/2026/a1", story("Js one")
        ),
        "https://wire.example/news/2026/a2/?utm_source=x": ok("x", story("Js two")),
    }
    browser = FakeBrowser(pages)
    result = run_collect(
        browser, mock_client(site_handler([])), cfg={**CFG, "render_articles": True}
    )
    assert sorted(i.title for i in result.items) == ["Js one", "Js two"]
    assert len(browser.calls) == 3


def test_index_failures_are_reported() -> None:
    client = mock_client(site_handler([]))
    assert "HTTP 404" in run_collect(FakeBrowser({}), client).error
    blocked = RenderedPage(INDEX, 403, "", "Access denied by robots.txt")
    assert "robots" in run_collect(FakeBrowser({INDEX: blocked}), client).error
    empty = FakeBrowser({INDEX: ok(INDEX, "<html><body>nothing</body></html>")})
    assert "no story links" in run_collect(empty, client).error


def make_web_source(factory, **config) -> int:
    with factory() as session, session.begin():
        return add_source(
            session, kind="web", locator=INDEX, name="Wire", language="en", config={**CFG, **config}
        ).id


def test_poll_web_source_end_to_end(factory, tmp_path: Path) -> None:
    requested: list[str] = []
    client = mock_client(site_handler(requested))
    store = SnapshotStore(tmp_path)
    browser = FakeBrowser({INDEX: ok(INDEX, INDEX_HTML)})
    sid = make_web_source(factory)

    first = poll_source(factory, client, RobotsCache("t"), store, sid, NOW, browser)
    assert (first.status, first.new_items) == ("ok", 2)
    with factory() as session:
        rows = session.scalars(select(RawItem).order_by(RawItem.external_id)).all()
        assert [r.external_id for r in rows] == [
            "https://wire.example/news/2026/a1",
            "https://wire.example/news/2026/a2",
        ]
        assert rows[0].language == "en" and rows[0].title == "Story a1"
        assert b"<article>" in store.get(rows[0].page_snapshot_ref)
        assert b'"source": "web"' in store.get(rows[0].snapshot_ref)
        source = session.get(Source, sid)
        assert source.poll_interval_s == 150 and "http" not in source.config

    fetched_before = len(requested)
    second = poll_source(factory, client, RobotsCache("t"), store, sid, NOW, browser)
    assert (second.status, second.new_items) == ("ok", 0)
    assert not [u for u in requested[fetched_before:] if "/news/2026/" in u]  # nothing refetched


def test_web_source_failure_modes(factory, tmp_path: Path) -> None:
    client = mock_client(site_handler([]))
    store = SnapshotStore(tmp_path)
    sid = make_web_source(factory)

    no_browser = poll_source(factory, client, RobotsCache("t"), store, sid, NOW, None)
    assert no_browser.status == "error" and "no browser" in no_browser.error

    class Broken:
        def render(self, *a, **k):
            raise BrowserUnavailable("chromium missing")

    broken = poll_source(factory, client, RobotsCache("t"), store, sid, NOW, Broken())
    assert broken.status == "error" and "chromium missing" in broken.error
    with factory() as session:
        source = session.get(Source, sid)
        assert source.consecutive_failures == 2 and source.poll_interval_s == 1200


# ---- real browser, opt-in -------------------------------------------------------------------

JS_INDEX = (
    "<html><head><title>Local Defence Wire</title></head><body><header><h1>Local Defence Wire</h1>"
    "<p>"
    + " ".join(SENTENCES)
    + """</p></header><ul id="n"></ul><script>
setTimeout(() => { for (const id of ["a1","a2"]) {
  const a = document.createElement("a"); a.className = "story";
  a.href = "/news/2026/" + id; a.textContent = "Story " + id;
  document.getElementById("n").append(a); } }, 300);
</script></body></html>"""
)


class LocalSite(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        routes = {
            "/news/": JS_INDEX,
            "/robots.txt": "User-agent: *\nDisallow: /private/\n",
            "/private/x": story("Internal memo"),
        }
        body = routes.get(self.path)
        if body is None and self.path.startswith("/news/2026/"):
            body = story(f"Story {self.path[-2:]}")
        self.send_response(200 if body is not None else 404)
        self.send_header(
            "Content-Type", "text/plain" if self.path == "/robots.txt" else "text/html"
        )
        self.end_headers()
        self.wfile.write((body or "not found").encode())

    def log_message(self, *args):
        pass


@pytest.mark.skipif(
    not os.environ.get("OSINT_TEST_BROWSER"),
    reason="needs Chromium and crawl4ai; set OSINT_TEST_BROWSER=1 (and OSINT_BROWSER_CDP_URL if "
    "Playwright's pinned browser is not installed)",
)
def test_real_browser_renders_js_links_and_honours_robots(factory, tmp_path: Path) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), LocalSite)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    browser = BrowserFetcher()
    try:
        plain = httpx.get(f"{base}/news/")
        assert "a.story" not in plain.text and 'class="story"' not in plain.text  # JS-built list

        page = browser.render(f"{base}/news/", wait_for="css:a.story")
        assert page.error is None
        links = extract_links(page.html, page.url, {"link_selector": "a.story"})
        assert [u.rsplit("/", 1)[1] for u in links] == ["a1", "a2"]

        denied = browser.render(f"{base}/private/x", respect_robots=True)
        assert denied.error and "robots" in denied.error.lower()
        allowed = browser.render(f"{base}/private/x", respect_robots=False)
        assert allowed.error is None and "Internal memo" in allowed.html

        with factory() as session, session.begin():
            sid = add_source(
                session,
                kind="web",
                locator=f"{base}/news/",
                name="Local",
                config={"link_selector": "a.story", "wait_for": "css:a.story"},
            ).id
        client = httpx.Client(headers={"User-Agent": "test"})
        outcome = poll_source(
            factory, client, RobotsCache("test"), SnapshotStore(tmp_path), sid, NOW, browser
        )
        assert (outcome.status, outcome.new_items) == ("ok", 2)
    finally:
        browser.close()
        server.shutdown()
