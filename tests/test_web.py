import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from osint.models import RawItem, Source
from osint.sources import add_source
from osint.web import create_app


@pytest.fixture
def client(factory, temp_database, monkeypatch):
    monkeypatch.setenv("OSINT_DATABASE_URL", temp_database)
    with factory() as session, session.begin():
        a = add_source(session, kind="rss", locator="https://a.example/f", name="Alpha")
        b = add_source(session, kind="rss", locator="https://b.example/f", name="Beta")
        for source, title in [
            (a, "Radar upgrade announced"),
            (b, "Fleet 100% ready"),
            (a, "Drone strike reported"),
            (b, "Budget_2027 approved"),
        ]:
            session.add(
                RawItem(
                    source_id=source.id,
                    external_id=title,
                    title=title,
                    url=f"https://x.example/{title}",
                    language="en",
                    analysis_status="pending",
                )
            )
    with TestClient(create_app()) as c:
        yield c


def test_index_serves_html(client) -> None:
    resp = client.get("/")
    assert resp.status_code == 200 and "OSINT Dashboard" in resp.text


def test_items_newest_first_with_source_name(client) -> None:
    data = client.get("/api/items").json()
    assert [d["title"] for d in data] == [
        "Budget_2027 approved",
        "Drone strike reported",
        "Fleet 100% ready",
        "Radar upgrade announced",
    ]
    assert data[0]["source"] == "Beta"


def test_items_pagination_and_filters(client) -> None:
    first = client.get("/api/items", params={"limit": 2}).json()
    assert len(first) == 2
    rest = client.get("/api/items", params={"offset": 2}).json()
    assert [d["title"] for d in rest] == ["Fleet 100% ready", "Radar upgrade announced"]

    alpha = next(d["source_id"] for d in client.get("/api/items").json() if d["source"] == "Alpha")
    only = client.get("/api/items", params={"source_id": alpha}).json()
    assert {d["source"] for d in only} == {"Alpha"}


def test_title_filter_is_case_insensitive_and_escapes_wildcards(client) -> None:
    titles = lambda q: [d["title"] for d in client.get("/api/items", params={"q": q}).json()]  # noqa: E731
    assert titles("DRONE") == ["Drone strike reported"]
    assert titles("100%") == ["Fleet 100% ready"]
    assert titles("%") == ["Fleet 100% ready"]  # a literal percent sign, not a wildcard
    assert titles("_") == ["Budget_2027 approved"]  # a literal underscore, not "any character"


def test_limit_is_validated(client) -> None:
    assert client.get("/api/items", params={"limit": 0}).status_code == 422
    assert client.get("/api/items", params={"limit": 501}).status_code == 422


def test_sources_report_counts_and_health(client) -> None:
    data = {s["name"]: s for s in client.get("/api/sources").json()}
    assert data["Alpha"]["items"] == 2 and data["Beta"]["items"] == 2
    assert data["Alpha"]["last_success_age_s"] is None
    assert data["Alpha"]["consecutive_failures"] == 0


def test_items_ordered_by_publication_not_insertion(factory, client) -> None:
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    with factory() as session, session.begin():
        source_id = session.scalar(select(Source.id).limit(1))
        for title, published in [
            ("Backfilled old article", now - timedelta(days=900)),
            ("Fresh article", now - timedelta(minutes=5)),
            ("Wrongly dated in the future", now + timedelta(days=30)),
        ]:
            session.add(
                RawItem(
                    source_id=source_id,
                    external_id=title,
                    title=title,
                    published_at=published,
                    analysis_status="pending",
                )
            )
    order = [d["title"] for d in client.get("/api/items", params={"limit": 100}).json()]
    # The future-dated item is capped at its collection time (just now), so it ranks with
    # the freshest items, and the 900-day-old backfill ranks below every undated item.
    assert order.index("Wrongly dated in the future") < order.index("Backfilled old article")
    assert order.index("Fresh article") < order.index("Backfilled old article")
    assert order[-1] == "Backfilled old article"


@pytest.fixture
def grouped_client(factory, temp_database, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from osint.dedup import group_pending, item_simhash
    from osint.urls import canonicalize_url, content_hash

    monkeypatch.setenv("OSINT_DATABASE_URL", temp_database)
    now = datetime.now(UTC)
    body = " ".join(f"w{i % 90}" for i in range(200))
    other = " ".join(f"z{i % 70}" for i in range(200))
    with factory() as session, session.begin():
        a = add_source(session, kind="rss", locator="https://a.example/f", name="Alpha")
        b = add_source(session, kind="rss", locator="https://b.example/f", name="Beta")
        for source, ext, title, text, published in [
            (b, "b1", "Shared story", body, now - timedelta(hours=1)),
            (a, "a1", "Shared story", body, now - timedelta(hours=2)),
            (a, "a2", "Another story", other, now - timedelta(minutes=10)),
        ]:
            session.add(
                RawItem(
                    source_id=source.id,
                    external_id=ext,
                    title=title,
                    content=text,
                    url=f"https://{source.name.lower()}.example/{ext}",
                    url_canonical=canonicalize_url(f"https://{source.name.lower()}.example/{ext}"),
                    published_at=published,
                    collected_at=now,
                    content_hash=content_hash(title, text),
                    simhash=item_simhash(title, text),
                    analysis_status="pending",
                )
            )
        session.flush()
        group_pending(session)
    with TestClient(create_app()) as c:
        yield c


def test_groups_list_collapses_reposts(grouped_client) -> None:
    data = grouped_client.get("/api/groups").json()
    assert [g["title"] for g in data] == ["Another story", "Shared story"]  # newest origin first
    shared = data[1]
    assert (shared["items"], shared["sources"], shared["source"]) == (2, 2, "Alpha")
    assert data[0]["items"] == 1


def test_group_evidence_shows_origin_and_delay(grouped_client) -> None:
    shared = next(g for g in grouped_client.get("/api/groups").json() if g["items"] == 2)
    detail = grouped_client.get(f"/api/groups/{shared['id']}").json()
    origin, repost = detail["evidence"]
    assert (origin["source"], origin["is_origin"], origin["behind_origin_s"]) == ("Alpha", True, 0)
    assert (repost["source"], repost["is_origin"]) == ("Beta", False)
    assert repost["behind_origin_s"] == 3600


def test_group_filter_and_unknown_group(grouped_client) -> None:
    hits = grouped_client.get("/api/groups", params={"q": "another"}).json()
    assert [g["title"] for g in hits] == ["Another story"]
    assert grouped_client.get("/api/groups/999999").status_code == 404
