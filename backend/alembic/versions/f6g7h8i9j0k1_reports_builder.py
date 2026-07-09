"""reports_builder — selfmade_report table for Section 9.9.

Revision ID: f6g7h8i9j0k1
Revises: e5f6g7h8i9j0
Create Date: 2026-07-10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "f6g7h8i9j0k1"
down_revision = "e5f6g7h8i9j0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "selfmade_report",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("category", sa.String(120), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column(
            "rule_version_id",
            sa.Integer(),
            sa.ForeignKey("selfmade_rule_version.id"),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(30),
            nullable=False,
            server_default="draft",
        ),
        # sections chosen: JSON bool flags  {exec_summary, top_funds, key_insights, methodology}
        sa.Column(
            "sections",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("exec_summary", sa.Text(), nullable=True),
        # [{schemecode, fund_name, rank, score, narrative}]
        sa.Column(
            "fund_narratives",
            postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
        # [{heading, body}]
        sa.Column(
            "key_insights",
            postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
        # {pass, flagged_phrases, suggested_rewrites: [{phrase, field, rewrite}]}
        sa.Column("compliance_result", postgresql.JSONB(), nullable=True),
        # Local path written by export endpoint
        sa.Column("export_pdf_path", sa.String(500), nullable=True),
        sa.Column("export_docx_path", sa.String(500), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    op.create_index(
        "ix_selfmade_report_created_at",
        "selfmade_report",
        [sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_selfmade_report_created_at", "selfmade_report")
    op.drop_table("selfmade_report")
