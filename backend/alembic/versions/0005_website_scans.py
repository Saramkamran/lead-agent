"""Add website_scans table and scan fields on leads

Revision ID: 0005
Revises: 0004
Create Date: 2026-03-18 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "website_scans",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("lead_id", sa.String(), nullable=False),
        sa.Column("business_type", sa.String(255), nullable=True),
        sa.Column("services_list", sa.Text(), nullable=True),
        sa.Column("has_pricing_page", sa.Boolean(), nullable=True),
        sa.Column("has_booking_system", sa.Boolean(), nullable=True),
        sa.Column("has_contact_form", sa.Boolean(), nullable=True),
        sa.Column("cta_strength", sa.String(50), nullable=True),
        sa.Column("lead_capture_forms", sa.Boolean(), nullable=True),
        sa.Column("design_quality", sa.String(50), nullable=True),
        sa.Column("booking_method", sa.String(100), nullable=True),
        sa.Column("detected_problem", sa.String(100), nullable=True),
        sa.Column("hook_text", sa.Text(), nullable=True),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_website_scans_lead_id", "website_scans", ["lead_id"])

    op.add_column("leads", sa.Column("scan_status", sa.String(50), nullable=True, server_default="pending"))
    op.add_column("leads", sa.Column("scan_retry_count", sa.Integer(), nullable=True, server_default="0"))
    op.add_column("leads", sa.Column("last_contacted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("leads", sa.Column("next_followup_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("leads", sa.Column("reply_category", sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column("leads", "reply_category")
    op.drop_column("leads", "next_followup_at")
    op.drop_column("leads", "last_contacted_at")
    op.drop_column("leads", "scan_retry_count")
    op.drop_column("leads", "scan_status")
    op.drop_index("ix_website_scans_lead_id", table_name="website_scans")
    op.drop_table("website_scans")
