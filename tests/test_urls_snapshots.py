from pathlib import Path

from osint.snapshots import SnapshotStore
from osint.urls import canonicalize_url, content_hash


def test_canonicalize_strips_tracking_and_fragment() -> None:
    url = "HTTPS://Example.ORG:443/News/Story/?utm_source=x&b=2&a=1&fbclid=zzz#top"
    assert canonicalize_url(url) == "https://example.org/News/Story?a=1&b=2"


def test_canonicalize_keeps_nondefault_port_and_root() -> None:
    assert canonicalize_url("http://example.org:8080") == "http://example.org:8080/"


def test_same_story_different_links_match() -> None:
    a = canonicalize_url("https://example.org/a/?utm_medium=rss")
    b = canonicalize_url("https://example.org/a")
    assert a == b


def test_content_hash_ignores_case_and_whitespace() -> None:
    assert content_hash("Hello  World", "Body\n text") == content_hash("hello world", "body text")
    assert content_hash("a", "b") != content_hash("a", "c")


def test_snapshot_roundtrip_and_write_once(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path)
    ref = store.put(b"<html>evidence</html>", "html")
    assert ref.endswith(".html.gz")
    assert store.get(ref) == b"<html>evidence</html>"

    path = tmp_path / ref
    mtime = path.stat().st_mtime_ns
    assert store.put(b"<html>evidence</html>", "html") == ref
    assert path.stat().st_mtime_ns == mtime  # existing evidence is never rewritten


def test_different_content_gets_different_ref(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path)
    assert store.put(b"one", "json") != store.put(b"two", "json")
