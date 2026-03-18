"""Add outreach_accounts table and leads.outreach_account_id

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-18 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "outreach_accounts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("smtp_host", sa.String(255), nullable=False),
        sa.Column("smtp_port", sa.Integer(), nullable=False, server_default="587"),
        sa.Column("smtp_user", sa.String(255), nullable=False),
        sa.Column("smtp_pass", sa.String(500), nullable=False),
        sa.Column("imap_host", sa.String(255), nullable=False),
        sa.Column("imap_port", sa.Integer(), nullable=False, server_default="993"),
        sa.Column("from_name", sa.String(100), nullable=False),
        sa.Column("from_email", sa.String(255), nullable=False),
        sa.Column("daily_limit", sa.Integer(), nullable=False, server_default="40"),
        sa.Column("leads_assigned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )

    op.add_column(
        "leads",
        sa.Column(
            "outreach_account_id",
            sa.String(),
            sa.ForeignKey("outreach_accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_leads_outreach_account_id", "leads", ["outreach_account_id"])


def downgrade() -> None:
    op.drop_index("ix_leads_outreach_account_id", table_name="leads")
    op.drop_column("leads", "outreach_account_id")
    op.drop_table("outreach_accounts")
