import threading
import time

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from osint.collectors.rss import ParsedItem
from osint.dedup import group_item, item_simhash, reconsider_exact
from osint.ingest import ingest_items
from osint.models import EventGroup, Evidence, RawItem, Source
from osint.snapshots import SnapshotStore
from osint.sources import add_source
from osint.urls import canonicalize_url, content_hash
from tests.test_dedup import article


def story(external_id: str) -> ParsedItem:
    return ParsedItem(
        external_id=external_id,
        url=f"https://example.org/{external_id}",
        title="Shared story",
        content=article(5),
        published_at=None,
        raw=b"{}",
    )


def counts(factory: sessionmaker) -> tuple[int, int]:
    with factory() as session:
        groups = session.scalar(select(func.count()).select_from(EventGroup))
        evidence = session.scalar(select(func.count()).select_from(Evidence))
    return groups, evidence


def test_concurrent_ingests_of_one_story_end_in_one_group(factory, tmp_path) -> None:
    with factory() as session, session.begin():
        a = add_source(session, kind="rss", locator="https://a.example/f", name="A").id
        b = add_source(session, kind="rss", locator="https://b.example/f", name="B").id
    store = SnapshotStore(tmp_path)
    finished = threading.Event()

    def second_poller() -> None:
        with factory() as session, session.begin():
            ingest_items(session, session.get(Source, b), [story("two")], store)
        finished.set()

    first = factory()
    first.begin()
    ingest_items(first, first.get(Source, a), [story("one")], store)  # holds the grouping lock

    worker = threading.Thread(target=second_poller)
    worker.start()
    time.sleep(0.5)
    assert not finished.is_set()  # the second poller waits instead of grouping blindly
    first.commit()
    first.close()
    worker.join(timeout=10)

    assert finished.is_set()
    assert counts(factory) == (1, 2)  # one story, both reports kept


def test_reconsider_exact_repairs_duplicate_groups(factory) -> None:
    with factory() as session, session.begin():
        a = add_source(session, kind="rss", locator="https://a.example/f", name="A")
        b = add_source(session, kind="rss", locator="https://b.example/f", name="B")
        ids = []
        for source, ext in ((a, "one"), (b, "two")):
            item = RawItem(
                source_id=source.id,
                external_id=ext,
                url=f"https://example.org/{ext}",
                url_canonical=canonicalize_url(f"https://example.org/{ext}"),
                title="Shared story",
                content=article(5),
                content_hash=content_hash("Shared story", article(5)),
                simhash=item_simhash("Shared story", article(5)),
                analysis_status="pending",
            )
            session.add(item)
            session.flush()
            group = EventGroup(
                title=item.title
            )  # as if both were grouped without seeing each other
            session.add(group)
            session.flush()
            session.add(Evidence(event_group_id=group.id, raw_item_id=item.id, is_origin=True))
            ids.append(item.id)
        session.flush()
    assert counts(factory) == (2, 2)

    with factory() as session, session.begin():
        assert reconsider_exact(session) == 1
    assert counts(factory) == (1, 2)
    with factory() as session, session.begin():
        assert reconsider_exact(session) == 0  # nothing left to repair
        assert group_item(session, ids[0]) == group_item(session, ids[1])
