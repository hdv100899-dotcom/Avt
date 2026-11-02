"""raw_item.title_vi / title_vi_model: machine translation of the headline into Vietnamese

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("raw_item", sa.Column("title_vi", sa.Text))
    op.add_column("raw_item", sa.Column("title_vi_model", sa.Text))


def downgrade() -> None:
    op.drop_column("raw_item", "title_vi_model")
    op.drop_column("raw_item", "title_vi")
