import httpx
import pytest

from osint.collectors.rss import fetch_feed, parse_feed

RSS = b"""<?xml version="1.0"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel><title>T</title>
<item>
  <title>First &amp; <b>foremost</b></title>
  <link>https://example.org/1</link>
  <guid>guid-1</guid>
  <pubDate>Mon, 20 Oct 2026 10:00:00 GMT</pubDate>
  <description>&lt;p&gt;Short teaser.&lt;/p&gt;</description>
  <content:encoded>&lt;p&gt;Full   body &lt;b&gt;text&lt;/b&gt;.&lt;/p&gt;</content:encoded>
</item>
<item>
  <title>No guid</title>
  <link>https://example.org/2</link>
</item>
<item>
  <title>No guid, no link</title>
  <pubDate>Mon, 20 Oct 2026 11:00:00 GMT</pubDate>
</item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>A</title>
<entry><title>Atom entry</title><id>tag:example.org,2026:1</id>
<link href="https://example.org/atom/1"/>
<updated>2026-10-20T09:30:00Z</updated><summary>Atom summary</summary></entry>
</feed>"""


def test_parse_rss_prefers_full_content_and_strips_markup() -> None:
    first, second, third = parse_feed(RSS)
    assert first.external_id == "guid-1"
    assert first.title == "First & foremost"
    assert first.content == "Full body text."
    assert first.published_at.isoformat() == "2026-10-20T10:00:00+00:00"
    assert first.url == "https://example.org/1"
    assert b"guid-1" in first.raw
    # Missing guid falls back to the link, then to a hash of title and date.
    assert second.external_id == "https://example.org/2"
    assert third.external_id.startswith("sha1:")
    assert second.published_at is None


def test_parse_atom() -> None:
    (item,) = parse_feed(ATOM)
    assert item.external_id == "tag:example.org,2026:1"
    assert item.url == "https://example.org/atom/1"
    assert item.content == "Atom summary"
    assert item.published_at.isoformat() == "2026-10-20T09:30:00+00:00"


def test_parse_rejects_non_feed() -> None:
    with pytest.raises(ValueError, match="not a valid feed"):
        parse_feed(b"<html><body>Please enable JavaScript</body></html>")


def test_parse_empty_valid_feed_gives_no_items() -> None:
    assert (
        parse_feed(
            b'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title></channel></rss>'
        )
        == []
    )


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_sends_validators_and_handles_304() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(304)

    result = fetch_feed(
        _client(handler),
        "https://example.org/f",
        {"etag": '"abc"', "last_modified": "Mon, 01 Jan 2026"},
    )
    assert result.kind == "not_modified"
    assert seen["if-none-match"] == '"abc"'
    assert seen["if-modified-since"] == "Mon, 01 Jan 2026"
    assert result.etag == '"abc"'


def test_fetch_returns_validators_from_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=RSS, headers={"ETag": '"v2"', "Last-Modified": "Tue"})

    result = fetch_feed(_client(handler), "https://example.org/f")
    assert (result.kind, result.etag, result.last_modified) == ("ok", '"v2"', "Tue")


def test_fetch_errors_do_not_raise() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow")

    assert fetch_feed(_client(boom), "https://example.org/f").kind == "error"
    status = fetch_feed(_client(lambda r: httpx.Response(503)), "https://example.org/f")
    assert (status.kind, status.error) == ("error", "HTTP 503")


def test_block_elements_do_not_glue_words_together() -> None:
    feed = (
        b'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title><item>'
        b"<title>x</title><guid>1</guid>"
        b"<description>&lt;div&gt;By Kemal&lt;/div&gt;The following list&lt;br/&gt;continues"
        b"&lt;p&gt;Second&lt;/p&gt;&lt;p&gt;para&lt;/p&gt;</description></item></channel></rss>"
    )
    (item,) = parse_feed(feed)
    assert item.content == "By Kemal The following list continues Second para"
