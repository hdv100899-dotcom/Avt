import typer

from osint.db import make_engine, make_session_factory
from osint.models import SOURCE_KINDS, SOURCE_STATUSES, SOURCE_TIERS
from osint.sources import SourceError, add_source, list_sources, set_status

app = typer.Typer(no_args_is_help=True, help="OSINT dashboard command line.")
source_app = typer.Typer(no_args_is_help=True, help="Manage the source registry.")
app.add_typer(source_app, name="source")


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
