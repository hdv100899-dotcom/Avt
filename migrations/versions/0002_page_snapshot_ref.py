"""raw_item.page_snapshot_ref: article page snapshot, separate from the feed entry

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("raw_item", sa.Column("page_snapshot_ref", sa.Text))


def downgrade() -> None:
    op.drop_column("raw_item", "page_snapshot_ref")
