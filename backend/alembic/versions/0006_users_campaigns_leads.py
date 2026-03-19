"""Add role/is_active to users, send_hour/send_minute to campaigns, send_fail_count to leads

Revision ID: 0006
Revises: 0005
Create Date: 2026-03-19 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # users: add role and is_active
    op.add_column("users", sa.Column("role", sa.String(20), nullable=False, server_default="user"))
    op.add_column("users", sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"))

    # Promote the earliest-created user to admin
    op.execute(
        "UPDATE users SET role = 'admin' "
        "WHERE id = (SELECT id FROM users ORDER BY created_at ASC LIMIT 1)"
    )

    # campaigns: add send_hour and send_minute
    op.add_column("campaigns", sa.Column("send_hour", sa.Integer(), nullable=False, server_default="9"))
    op.add_column("campaigns", sa.Column("send_minute", sa.Integer(), nullable=False, server_default="0"))

    # leads: add send_fail_count
    op.add_column("leads", sa.Column("send_fail_count", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("leads", "send_fail_count")
    op.drop_column("campaigns", "send_minute")
    op.drop_column("campaigns", "send_hour")
    op.drop_column("users", "is_active")
    op.drop_column("users", "role")
