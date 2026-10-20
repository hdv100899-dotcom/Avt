"""raw_item.simhash for near-duplicate detection

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("raw_item", sa.Column("simhash", sa.BigInteger))


def downgrade() -> None:
    op.drop_column("raw_item", "simhash")
