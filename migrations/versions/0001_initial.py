"""initial schema: source, raw_item, event_group, evidence

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Needed from phase 3 (embedding clustering); created now so every environment
    # is verified to have the extension before any data exists.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "source",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("locator", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("tier", sa.Text, nullable=False),
        sa.Column("language", sa.Text),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("trust_score", sa.Float, nullable=False),
        sa.Column("poll_interval_s", sa.Integer, nullable=False),
        sa.Column(
            "config",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("discovered_from_id", sa.BigInteger, sa.ForeignKey("source.id")),
        sa.Column("last_polled_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_item_at", sa.DateTime(timezone=True)),
        sa.Column("consecutive_failures", sa.Integer, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("kind", "locator", name="uq_source_kind_locator"),
        sa.CheckConstraint(
            "kind IN ('rss', 'web', 'telegram', 'bluesky', 'mastodon', 'manual')",
            name="ck_source_kind",
        ),
        sa.CheckConstraint("tier IN ('A', 'B', 'C', 'D')", name="ck_source_tier"),
        sa.CheckConstraint(
            "status IN ('probation', 'active', 'paused', 'rejected')", name="ck_source_status"
        ),
        sa.CheckConstraint("trust_score >= 0 AND trust_score <= 1", name="ck_source_trust_score"),
        sa.CheckConstraint("poll_interval_s > 0", name="ck_source_poll_interval"),
    )

    op.create_table(
        "raw_item",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("source_id", sa.BigInteger, sa.ForeignKey("source.id"), nullable=False),
        sa.Column("external_id", sa.Text, nullable=False),
        sa.Column("url", sa.Text),
        sa.Column("url_canonical", sa.Text),
        sa.Column("title", sa.Text),
        sa.Column("content", sa.Text),
        sa.Column("language", sa.Text),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column(
            "collected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("content_hash", sa.Text),
        sa.Column("snapshot_ref", sa.Text),
        sa.Column("analysis_status", sa.Text, nullable=False),
        sa.UniqueConstraint("source_id", "external_id", name="uq_raw_item_source_external"),
        sa.CheckConstraint(
            "analysis_status IN ('pending', 'done', 'failed')", name="ck_raw_item_analysis"
        ),
    )
    op.create_index("ix_raw_item_content_hash", "raw_item", ["content_hash"])
    op.create_index("ix_raw_item_url_canonical", "raw_item", ["url_canonical"])
    op.create_index("ix_raw_item_collected_at", "raw_item", [sa.text("collected_at DESC")])

    op.create_table(
        "event_group",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("title", sa.Text),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    op.create_table(
        "evidence",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("event_group_id", sa.BigInteger, sa.ForeignKey("event_group.id"), nullable=False),
        sa.Column(
            "raw_item_id",
            sa.BigInteger,
            sa.ForeignKey("raw_item.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("is_origin", sa.Boolean, nullable=False),
        sa.Column(
            "added_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "uq_evidence_one_origin_per_group",
        "evidence",
        ["event_group_id"],
        unique=True,
        postgresql_where=sa.text("is_origin"),
    )


def downgrade() -> None:
    op.drop_table("evidence")
    op.drop_table("event_group")
    op.drop_table("raw_item")
    op.drop_table("source")
