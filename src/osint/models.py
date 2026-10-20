"""Core schema.

Evidence is kept apart from events: every collected post is a raw_item and is never
merged away. An event_group is a view over many raw_items through evidence rows, so a
story reposted by 15 accounts keeps 15 evidence rows under one group.
"""

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SOURCE_KINDS = ("rss", "web", "telegram", "bluesky", "mastodon", "manual")
SOURCE_TIERS = ("A", "B", "C", "D")
SOURCE_STATUSES = ("probation", "active", "paused", "rejected")
ANALYSIS_STATUSES = ("pending", "done", "failed")
EMBEDDING_DIM = 384  # paraphrase-multilingual-MiniLM-L12-v2


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Base(DeclarativeBase):
    pass


class Source(Base):
    __tablename__ = "source"
    __table_args__ = (
        UniqueConstraint("kind", "locator", name="uq_source_kind_locator"),
        CheckConstraint(_in("kind", SOURCE_KINDS), name="ck_source_kind"),
        CheckConstraint(_in("tier", SOURCE_TIERS), name="ck_source_tier"),
        CheckConstraint(_in("status", SOURCE_STATUSES), name="ck_source_status"),
        CheckConstraint("trust_score >= 0 AND trust_score <= 1", name="ck_source_trust_score"),
        CheckConstraint("poll_interval_s > 0", name="ck_source_poll_interval"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(Text)
    # Feed URL, channel handle, DID, ... depending on kind.
    locator: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    tier: Mapped[str] = mapped_column(Text, default="B")
    language: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="active")
    trust_score: Mapped[float] = mapped_column(Float, default=0.5)
    poll_interval_s: Mapped[int] = mapped_column(Integer, default=300)
    config: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    discovered_from_id: Mapped[int | None] = mapped_column(ForeignKey("source.id"))
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_item_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RawItem(Base):
    __tablename__ = "raw_item"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_raw_item_source_external"),
        CheckConstraint(_in("analysis_status", ANALYSIS_STATUSES), name="ck_raw_item_analysis"),
        Index("ix_raw_item_content_hash", "content_hash"),
        Index("ix_raw_item_url_canonical", "url_canonical"),
        Index("ix_raw_item_collected_at", text("collected_at DESC")),
        Index(
            "ix_raw_item_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("source.id"))
    external_id: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    url_canonical: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    content_hash: Mapped[str | None] = mapped_column(Text)
    # 64-bit SimHash of title and body; NULL when the text is too short to compare.
    simhash: Mapped[int | None] = mapped_column(BigInteger)
    # Sentence embedding of title and lede, for grouping reports of the same event that
    # share no wording. embedding_model records which model produced it.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    embedding_model: Mapped[str | None] = mapped_column(Text)
    # Pointers into the immutable evidence store: the feed entry as received, and the
    # article page when it was fetched for full text.
    snapshot_ref: Mapped[str | None] = mapped_column(Text)
    page_snapshot_ref: Mapped[str | None] = mapped_column(Text)
    analysis_status: Mapped[str] = mapped_column(Text, default="pending")


class EventGroup(Base):
    __tablename__ = "event_group"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str | None] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (
        # At most one origin (first publisher) per group; the rest are reposts.
        Index(
            "uq_evidence_one_origin_per_group",
            "event_group_id",
            unique=True,
            postgresql_where=text("is_origin"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_group_id: Mapped[int] = mapped_column(ForeignKey("event_group.id"))
    # A raw_item belongs to exactly one group.
    raw_item_id: Mapped[int] = mapped_column(ForeignKey("raw_item.id"), unique=True)
    is_origin: Mapped[bool] = mapped_column(Boolean, default=False)
    # How the item joined its group ("url", "content_hash", "simhash", "semantic"); NULL for the
    # item that started the group. match_score is the cosine similarity for "semantic".
    match_reason: Mapped[str | None] = mapped_column(Text)
    match_score: Mapped[float | None] = mapped_column(Float)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
