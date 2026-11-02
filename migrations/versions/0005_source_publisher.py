"""source.publisher: several feeds of one outlet count as one source

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("source", sa.Column("publisher", sa.Text))


def downgrade() -> None:
    op.drop_column("source", "publisher")
