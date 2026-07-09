"""Add comparison_session table.

Revision ID: d4e5f6g7h8i9
Revises: c3d4e5f6g7h8
Create Date: 2025-06-09 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d4e5f6g7h8i9"
down_revision: Union[str, None] = "c3d4e5f6g7h8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "comparison_session",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("fund_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("label", sa.String(200), nullable=True),
        sa.Column("is_saved", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_comparison_session_created_at", "comparison_session", ["created_at"])
    op.create_index("ix_comparison_session_is_saved", "comparison_session", ["is_saved"])


def downgrade() -> None:
    op.drop_index("ix_comparison_session_is_saved", "comparison_session")
    op.drop_index("ix_comparison_session_created_at", "comparison_session")
    op.drop_table("comparison_session")
