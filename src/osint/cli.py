import json
import logging
from datetime import timedelta
from pathlib import Path

import typer
from sqlalchemy import func, select

from osint.config import data_dir
from osint.db import make_engine, make_session_factory
from osint.dedup import backfill_simhash, group_pending
from osint.embeddings import FastEmbedder
from osint.models import SOURCE_KINDS, SOURCE_STATUSES, SOURCE_TIERS, Evidence, RawItem, Source
from osint.runner import make_client, run_forever, run_once
from osint.semantic import cluster_step, reconsider_singletons
from osint.snapshots import SnapshotStore
from osint.sources import SourceError, add_source, list_sources, set_status

app = typer.Typer(no_args_is_help=True, help="OSINT dashboard command line.")
source_app = typer.Typer(no_args_is_help=True, help="Manage the source registry.")
collect_app = typer.Typer(no_args_is_help=True, help="Run the collectors.")
app.add_typer(source_app, name="source")
app.add_typer(collect_app, name="collect")


def _setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _session():
    return make_session_factory(make_engine())()


@source_app.command("add")
def source_add(
    kind: str = typer.Argument(..., help=f"One of: {', '.join(SOURCE_KINDS)}"),
    locator: str = typer.Argument(..., help="Feed URL, channel handle, DID, ..."),
    name: str = typer.Option(..., "--name", "-n"),
    tier: str = typer.Option("B", help=f"One of: {', '.join(SOURCE_TIERS)}"),
    language: str | None = typer.Option(None, help="ISO 639-1 code, e.g. en"),
    interval: int = typer.Option(300, help="Poll interval in seconds"),
) -> None:
    with _session() as session, session.begin():
        try:
            source = add_source(
                session,
                kind=kind,
                locator=locator,
                name=name,
                tier=tier,
                language=language,
                poll_interval_s=interval,
            )
        except SourceError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(1) from exc
        typer.echo(f"added source {source.id}: {source.kind} {source.locator} ({source.status})")


@source_app.command("list")
def source_list(
    status: str | None = typer.Option(None, help=f"One of: {', '.join(SOURCE_STATUSES)}"),
) -> None:
    with _session() as session:
        for s in list_sources(session, status):
            typer.echo(f"{s.id}\t{s.status}\t{s.tier}\t{s.kind}\t{s.language or '-'}\t{s.name}")


@source_app.command("set-status")
def source_set_status(source_id: int, status: str) -> None:
    with _session() as session, session.begin():
        try:
            source = set_status(session, source_id, status)
        except SourceError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(1) from exc
        typer.echo(f"source {source.id} is now {source.status}")


@source_app.command("seed")
def source_seed(path: Path = typer.Argument(..., exists=True, dir_okay=False)) -> None:
    """Add every source in a JSON file; sources that already exist are skipped."""
    entries = json.loads(path.read_text())
    added = skipped = 0
    with _session() as session, session.begin():
        for entry in entries:
            try:
                add_source(session, **entry)
                added += 1
            except SourceError as exc:
                if "already exists" not in str(exc):
                    typer.echo(f"error: {entry.get('name')}: {exc}", err=True)
                    raise typer.Exit(1) from exc
                skipped += 1
    typer.echo(f"added {added}, skipped {skipped} existing")


@collect_app.command("once")
def collect_once(workers: int = typer.Option(8, help="Concurrent polls")) -> None:
    """Poll every source that is due, once, and print the outcome."""
    _setup_logging()
    factory = make_session_factory(make_engine())
    with make_client() as client:
        outcomes = run_once(factory, client, SnapshotStore(data_dir()), workers=workers)
    with factory() as session:
        names = dict(session.execute(select(Source.id, Source.name)).all())
    for o in outcomes:
        detail = f" {o.error}" if o.error else ""
        typer.echo(f"{names.get(o.source_id, o.source_id)}\t{o.status}\t+{o.new_items}{detail}")
    typer.echo(f"{sum(o.new_items for o in outcomes)} new items from {len(outcomes)} sources")


@collect_app.command("run")
def collect_run(
    workers: int = typer.Option(8, help="Concurrent polls"),
    tick: float = typer.Option(10, help="Seconds between scheduler passes"),
    embed: bool = typer.Option(True, help="Also embed new items and group same-event reports"),
) -> None:
    """Run the collector continuously until interrupted."""
    _setup_logging()
    factory = make_session_factory(make_engine())
    with make_client() as client:
        try:
            run_forever(
                factory,
                client,
                SnapshotStore(data_dir()),
                workers=workers,
                tick_s=tick,
                embedder=FastEmbedder() if embed else None,
            )
        except KeyboardInterrupt:
            typer.echo("stopped")


@app.command("web")
def web(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Serve the dashboard."""
    import uvicorn

    uvicorn.run("osint.web:create_app", factory=True, host=host, port=port)


@app.command("stats")
def stats() -> None:
    """Per-source item counts and median delay between publication and collection.

    The first poll of a source backfills old articles, so the delay only counts items
    collected more than ten minutes after the source was added.
    """
    with _session() as session:
        delay = (
            func.percentile_cont(0.5)
            .within_group(func.extract("epoch", RawItem.collected_at - RawItem.published_at))
            .filter(RawItem.collected_at > Source.created_at + timedelta(minutes=10))
        )
        rows = session.execute(
            select(Source.name, Source.poll_interval_s, func.count(RawItem.id), delay)
            .outerjoin(RawItem, RawItem.source_id == Source.id)
            .group_by(Source.id)
            .order_by(Source.id)
        ).all()
    for name, interval, count, median in rows:
        lag = f"{median / 60:.1f} min" if median is not None else "-"
        typer.echo(f"{name}\titems={count}\tinterval={interval}s\tmedian_lag={lag}")


@app.command("dedup")
def dedup(batch: int = typer.Option(500, help="Items grouped per transaction")) -> None:
    """Catch up: compute missing SimHashes and group every item that has no group yet."""
    factory = make_session_factory(make_engine())
    with factory() as session, session.begin():
        filled = backfill_simhash(session)
    grouped = 0
    while True:
        with factory() as session, session.begin():
            done = group_pending(session, limit=batch)
        grouped += done
        if done == 0:
            break
    with factory() as session:
        per_group = (
            select(func.count().label("n")).select_from(Evidence).group_by(Evidence.event_group_id)
        ).subquery()
        groups, multi, items = session.execute(
            select(
                func.count(),
                func.count().filter(per_group.c.n > 1),
                func.coalesce(func.sum(per_group.c.n), 0),
            )
        ).one()
    typer.echo(f"simhash filled: {filled}; items grouped now: {grouped}")
    typer.echo(f"{items} items in {groups} groups; {multi} groups have more than one item")


@app.command("cluster")
def cluster(
    batch: int = typer.Option(64, help="Items embedded per transaction"),
    threads: int | None = typer.Option(None, help="CPU threads for the model"),
    reconsider: bool = typer.Option(
        False, help="Also re-examine items that are alone in their group (after a threshold change)"
    ),
) -> None:
    """Embed every item that has no embedding and group reports of the same event."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    factory = make_session_factory(make_engine())
    embedder = FastEmbedder(threads)
    embedded = joined = 0
    while True:
        done, merged = cluster_step(factory, embedder, batch)
        embedded += done
        joined += merged
        if done == 0:
            break
        typer.echo(f"embedded {embedded} items so far, {joined} joined an existing event")
    if reconsider:
        with factory() as session, session.begin():
            again = reconsider_singletons(session)
        typer.echo(f"reconsidered lone items: {again} joined an existing event")
    typer.echo(f"done: {embedded} embedded, {joined} joined an existing event")
