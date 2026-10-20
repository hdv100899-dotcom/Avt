from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from typer.testing import CliRunner

from osint.cli import app
from osint.models import RawItem, Source
from osint.sources import add_source


def test_stats_reports_median_lag_and_ignores_backfill(factory, temp_database, monkeypatch) -> None:
    monkeypatch.setenv("OSINT_DATABASE_URL", temp_database)
    now = datetime.now(UTC)
    with factory() as session, session.begin():
        source = add_source(session, kind="rss", locator="https://a.example/f", name="Alpha")
        add_source(session, kind="rss", locator="https://b.example/f", name="Quiet")
        session.execute(
            update(Source).where(Source.id == source.id).values(created_at=now - timedelta(hours=2))
        )
        # Backfill: collected right after the source was added, published long ago.
        # Live: collected two hours later, published 2, 4 and 6 minutes earlier.
        rows = [(now - timedelta(hours=2) + timedelta(seconds=5), now - timedelta(days=700))]
        rows += [(now, now - timedelta(minutes=m)) for m in (2, 4, 6)]
        for i, (collected, published) in enumerate(rows):
            session.add(
                RawItem(
                    source_id=source.id,
                    external_id=str(i),
                    published_at=published,
                    collected_at=collected,
                    analysis_status="pending",
                )
            )

    result = CliRunner().invoke(app, ["stats"])

    assert result.exit_code == 0, result.output
    lines = {line.split("\t")[0]: line for line in result.output.strip().splitlines()}
    assert "items=4" in lines["Alpha"] and "median_lag=4.0 min" in lines["Alpha"]
    assert "items=0" in lines["Quiet"] and "median_lag=-" in lines["Quiet"]
