"""M4 — governance, chat, data quality exception tables.

Revision ID: c3d4e5f6g7h8
Revises: b2c3d4e5f6a7
Create Date: 2024-11-22 00:00:00.000000

New tables:
  approval_request, approval_comment, audit_event,
  chat_thread, chat_message, tool_call_log,
  data_quality_exception
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3d4e5f6g7h8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Governance ────────────────────────────────────────────────────────
    op.create_table(
        "approval_request",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "rule_version_id",
            sa.String(100),
            sa.ForeignKey("rule_version.id"),
            nullable=False,
        ),
        sa.Column(
            "submitted_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "approved", "rejected", "changes_requested",
                name="approval_status",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("rationale", sa.Text()),
        sa.Column("reviewer_note", sa.Text()),
        sa.Column(
            "reviewed_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_approval_request_rule_version_id", "approval_request", ["rule_version_id"])
    op.create_index("ix_approval_request_status", "approval_request", ["status"])

    op.create_table(
        "approval_comment",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("approval_request.id"),
            nullable=False,
        ),
        sa.Column(
            "author_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_approval_comment_request_id", "approval_comment", ["request_id"])

    op.create_table(
        "audit_event",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "actor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("entity_id", sa.String(200), nullable=False),
        sa.Column("detail", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_audit_event_action", "audit_event", ["action"])
    op.create_index("ix_audit_event_created_at", "audit_event", ["created_at"])

    # ── Chat ──────────────────────────────────────────────────────────────
    op.create_table(
        "chat_thread",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("title", sa.String(500)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "chat_message",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "thread_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chat_thread.id"),
            nullable=False,
        ),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sources", postgresql.JSONB()),
        sa.Column("intent", sa.String(100)),
        sa.Column("confidence", sa.String(20)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_chat_message_thread_id", "chat_message", ["thread_id"])

    op.create_table(
        "tool_call_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "message_id",
            sa.BigInteger(),
            sa.ForeignKey("chat_message.id"),
            nullable=True,
        ),
        sa.Column(
            "thread_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chat_thread.id"),
            nullable=True,
        ),
        sa.Column("tool_name", sa.String(100), nullable=False),
        sa.Column("input_json", postgresql.JSONB()),
        sa.Column("output_json", postgresql.JSONB()),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("status", sa.String(20), nullable=False, server_default="ok"),
        sa.Column("error_detail", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_tool_call_log_tool_name", "tool_call_log", ["tool_name"])
    op.create_index("ix_tool_call_log_message_id", "tool_call_log", ["message_id"])

    # ── Data quality exceptions ───────────────────────────────────────────
    op.create_table(
        "data_quality_exception",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("domain", sa.String(50), nullable=False),
        sa.Column(
            "severity",
            sa.Enum("blocking", "warning", "info", name="exception_severity"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("open", "acknowledged", "resolved", name="exception_status"),
            nullable=False,
            server_default="open",
        ),
        sa.Column("scheme_plan_id", sa.String(100)),
        sa.Column("benchmark_id", sa.String(100)),
        sa.Column("affected_date", sa.String(20)),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text()),
        sa.Column("ingestion_run_id", sa.Integer()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_dqe_domain", "data_quality_exception", ["domain"])
    op.create_index("ix_dqe_severity", "data_quality_exception", ["severity"])
    op.create_index("ix_dqe_status", "data_quality_exception", ["status"])


def downgrade() -> None:
    op.drop_table("data_quality_exception")
    op.drop_table("tool_call_log")
    op.drop_table("chat_message")
    op.drop_table("chat_thread")
    op.drop_table("audit_event")
    op.drop_table("approval_comment")
    op.drop_table("approval_request")

    op.execute("DROP TYPE IF EXISTS exception_status")
    op.execute("DROP TYPE IF EXISTS exception_severity")
    op.execute("DROP TYPE IF EXISTS approval_status")
