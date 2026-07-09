"""Add rule-approval governance columns and selfmade_audit_event table.

Adds submitted_by and parent_version_id to selfmade_rule_version, and creates
the selfmade_audit_event table used by the Rule Approval page's audit strip.

Revision ID: e5f6g7h8i9j0
Revises: d4e5f6g7h8i9
Create Date: 2026-07-10 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e5f6g7h8i9j0"
down_revision: Union[str, None] = "d4e5f6g7h8i9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE selfmade_rule_version
        ADD COLUMN IF NOT EXISTS submitted_by VARCHAR(255)
    """)
    op.execute("""
        ALTER TABLE selfmade_rule_version
        ADD COLUMN IF NOT EXISTS parent_version_id INTEGER
            REFERENCES selfmade_rule_version(id)
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS selfmade_audit_event (
            id          SERIAL PRIMARY KEY,
            action      VARCHAR(100)  NOT NULL,
            actor       VARCHAR(255)  NOT NULL,
            rule_version_id INTEGER,
            comment     TEXT,
            created_at  TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_selfmade_audit_event_created_at
        ON selfmade_audit_event (created_at DESC)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_selfmade_audit_event_created_at")
    op.execute("DROP TABLE IF EXISTS selfmade_audit_event")
    op.execute("ALTER TABLE selfmade_rule_version DROP COLUMN IF EXISTS parent_version_id")
    op.execute("ALTER TABLE selfmade_rule_version DROP COLUMN IF EXISTS submitted_by")
