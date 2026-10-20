"""raw_item embeddings (pgvector) and evidence.match_reason / match_score

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("raw_item", sa.Column("embedding", Vector(384)))
    op.add_column("raw_item", sa.Column("embedding_model", sa.Text))
    op.create_index(
        "ix_raw_item_embedding",
        "raw_item",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.add_column("evidence", sa.Column("match_reason", sa.Text))
    op.add_column("evidence", sa.Column("match_score", sa.Float))


def downgrade() -> None:
    op.drop_column("evidence", "match_score")
    op.drop_column("evidence", "match_reason")
    op.drop_index("ix_raw_item_embedding", table_name="raw_item")
    op.drop_column("raw_item", "embedding_model")
    op.drop_column("raw_item", "embedding")
