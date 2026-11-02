"""raw_item.relevance / relevance_version: military-relevance margin from the local classifier

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("raw_item", sa.Column("relevance", sa.Float))
    op.add_column("raw_item", sa.Column("relevance_version", sa.Text))


def downgrade() -> None:
    op.drop_column("raw_item", "relevance_version")
    op.drop_column("raw_item", "relevance")
