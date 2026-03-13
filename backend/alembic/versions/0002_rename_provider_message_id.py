"""Rename sendgrid_id to provider_message_id

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("messages", "sendgrid_id", new_column_name="provider_message_id")


def downgrade() -> None:
    op.alter_column("messages", "provider_message_id", new_column_name="sendgrid_id")
