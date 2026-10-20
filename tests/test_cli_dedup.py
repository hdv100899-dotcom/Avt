from typer.testing import CliRunner

from osint.cli import app
from osint.models import RawItem
from osint.sources import add_source
from osint.urls import content_hash

BODY = " ".join(f"w{i % 90}" for i in range(200))


def test_dedup_command_backfills_simhash_and_groups(factory, temp_database, monkeypatch) -> None:
    monkeypatch.setenv("OSINT_DATABASE_URL", temp_database)
    with factory() as session, session.begin():
        a = add_source(session, kind="rss", locator="https://a.example/f", name="A")
        b = add_source(session, kind="rss", locator="https://b.example/f", name="B")
        for source, ext in [(a, "1"), (b, "2")]:
            session.add(
                RawItem(
                    source_id=source.id,
                    external_id=ext,
                    title="Same",
                    content=BODY,
                    url=f"https://{source.name}.example/{ext}",
                    content_hash=content_hash("Same", BODY),
                    analysis_status="pending",
                )
            )  # stored by an older version: no simhash, no group

    first = CliRunner().invoke(app, ["dedup"])
    assert first.exit_code == 0, first.output
    assert "simhash filled: 2; items grouped now: 2" in first.output
    assert "2 items in 1 groups; 1 groups have more than one item" in first.output

    second = CliRunner().invoke(app, ["dedup"])
    assert "simhash filled: 0; items grouped now: 0" in second.output
