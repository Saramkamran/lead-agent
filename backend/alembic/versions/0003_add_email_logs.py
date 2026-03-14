"""Add email_logs table

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-14 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "email_logs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("lead_id", sa.String(), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=True),
        sa.Column("direction", sa.String(20), nullable=False, server_default="outbound"),
        sa.Column("message_id", sa.String(255), nullable=True),
        sa.Column("subject", sa.String(500), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_email_logs_message_id", "email_logs", ["message_id"])
    op.create_index("ix_email_logs_lead_id", "email_logs", ["lead_id"])


def downgrade() -> None:
    op.drop_index("ix_email_logs_lead_id", table_name="email_logs")
    op.drop_index("ix_email_logs_message_id", table_name="email_logs")
    op.drop_table("email_logs")
