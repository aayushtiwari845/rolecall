"""companies.probed_at: when discovery last looked for this company's boards

Revision ID: c4e1a9d27b10
Revises: bdd33cd25fe6
Create Date: 2026-11-26 22:10:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c4e1a9d27b10"
down_revision: Union[str, Sequence[str], None] = "bdd33cd25fe6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("probed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("companies", "probed_at")
