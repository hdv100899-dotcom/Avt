"""Write collected items to the database. Raw items are stored first and never merged."""

from dataclasses import dataclass

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from osint.collectors.rss import ParsedItem
from osint.dedup import group_item, item_simhash
from osint.models import RawItem, Source
from osint.snapshots import SnapshotStore
from osint.urls import canonicalize_url, content_hash


@dataclass
class NewItem:
    id: int
    url: str | None
    content: str | None


def ingest_items(
    session: Session, source: Source, items: list[ParsedItem], store: SnapshotStore
) -> list[NewItem]:
    """Insert items not seen before for this source and group them; return the new ones."""
    if not items:
        return []
    by_external_id = {it.external_id: it for it in items}
    rows = []
    for it in by_external_id.values():
        rows.append(
            {
                "source_id": source.id,
                "external_id": it.external_id,
                "url": it.url,
                "url_canonical": canonicalize_url(it.url) if it.url else None,
                "title": it.title,
                "content": it.content,
                "language": source.language,
                "published_at": it.published_at,
                "content_hash": content_hash(it.title, it.content),
                "simhash": item_simhash(it.title, it.content),
                "snapshot_ref": store.put(it.raw, "json"),
                "analysis_status": "pending",
            }
        )
    stmt = (
        pg_insert(RawItem)
        .values(rows)
        .on_conflict_do_nothing(constraint="uq_raw_item_source_external")
        .returning(RawItem.id, RawItem.external_id)
    )
    inserted = sorted(session.execute(stmt).all(), key=lambda row: row.id)
    # Grouped in the same transaction, so an item is never visible without its group.
    for row in inserted:
        group_item(session, row.id)
    return [
        NewItem(
            id=row.id,
            url=by_external_id[row.external_id].url,
            content=by_external_id[row.external_id].content,
        )
        for row in inserted
    ]
