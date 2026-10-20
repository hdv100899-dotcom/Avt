import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from osint.models import Base, EventGroup, Evidence, RawItem
from osint.sources import add_source
from tests.conftest import alembic_config


def test_migrations_match_models(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_vector_extension_installed(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as conn:
        found = conn.scalar(text("SELECT extname FROM pg_extension WHERE extname = 'vector'"))
    assert found == "vector"


def test_downgrade_then_upgrade(temp_database: str) -> None:
    cfg = alembic_config(temp_database)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    engine = create_engine(temp_database)
    try:
        assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    finally:
        engine.dispose()
    command.upgrade(cfg, "head")


def _item(session: Session, source_id: int, external_id: str) -> RawItem:
    item = RawItem(source_id=source_id, external_id=external_id, analysis_status="pending")
    session.add(item)
    session.flush()
    return item


def test_one_group_keeps_all_fifteen_evidence_rows(session: Session) -> None:
    source = add_source(session, kind="rss", locator="https://example.org/feed", name="Example")
    group = EventGroup(title="Reposted story")
    session.add(group)
    session.flush()

    for i in range(15):
        item = _item(session, source.id, f"post-{i}")
        session.add(Evidence(event_group_id=group.id, raw_item_id=item.id, is_origin=(i == 0)))
    session.flush()

    count = session.scalar(
        text("SELECT count(*) FROM evidence WHERE event_group_id = :g"), {"g": group.id}
    )
    assert count == 15


def test_group_allows_only_one_origin(session: Session) -> None:
    source = add_source(session, kind="rss", locator="https://example.org/feed", name="Example")
    group = EventGroup()
    session.add(group)
    session.flush()
    a = _item(session, source.id, "a")
    b = _item(session, source.id, "b")
    session.add(Evidence(event_group_id=group.id, raw_item_id=a.id, is_origin=True))
    session.flush()

    session.add(Evidence(event_group_id=group.id, raw_item_id=b.id, is_origin=True))
    with pytest.raises(IntegrityError), session.begin_nested():
        session.flush()


def test_raw_item_belongs_to_one_group(session: Session) -> None:
    source = add_source(session, kind="rss", locator="https://example.org/feed", name="Example")
    g1, g2 = EventGroup(), EventGroup()
    session.add_all([g1, g2])
    session.flush()
    item = _item(session, source.id, "a")
    session.add(Evidence(event_group_id=g1.id, raw_item_id=item.id, is_origin=False))
    session.flush()

    session.add(Evidence(event_group_id=g2.id, raw_item_id=item.id, is_origin=False))
    with pytest.raises(IntegrityError), session.begin_nested():
        session.flush()


def test_same_external_id_rejected_per_source(session: Session) -> None:
    source = add_source(session, kind="rss", locator="https://example.org/feed", name="Example")
    _item(session, source.id, "dup")

    session.add(RawItem(source_id=source.id, external_id="dup", analysis_status="pending"))
    with pytest.raises(IntegrityError), session.begin_nested():
        session.flush()
