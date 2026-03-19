"""Add enhanced intelligence fields to website_scans

Revision ID: 0007
Revises: 0006
Create Date: 2026-03-19 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("website_scans", sa.Column("pain_points", sa.Text(), nullable=True))
    op.add_column("website_scans", sa.Column("growth_signals", sa.Text(), nullable=True))
    op.add_column("website_scans", sa.Column("trust_signals", sa.Text(), nullable=True))
    op.add_column("website_scans", sa.Column("social_links", sa.Text(), nullable=True))
    op.add_column("website_scans", sa.Column("urgency_level", sa.String(10), nullable=True))
    op.add_column("website_scans", sa.Column("connection_angle", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("website_scans", "connection_angle")
    op.drop_column("website_scans", "urgency_level")
    op.drop_column("website_scans", "social_links")
    op.drop_column("website_scans", "trust_signals")
    op.drop_column("website_scans", "growth_signals")
    op.drop_column("website_scans", "pain_points")
