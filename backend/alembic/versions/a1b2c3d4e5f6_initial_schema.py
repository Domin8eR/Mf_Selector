"""Initial schema — all foundation tables.

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2024-11-20 00:00:00.000000

Tables created:
  firms, users, trading_calendar, benchmarks, schemes,
  data_versions, nav_raw, nav_production,
  benchmark_nav_raw, benchmark_nav_production

Extensions enabled:
  pgvector (for AI/RAG embeddings in later milestones)
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgvector extension (used by AI/RAG layer in later milestones).
    # pgvector extension — silently skipped if not installed on this Postgres.
    # Required only for the RAG/AI embedding features (milestone 5+).
    op.execute(
        """
        DO $$
        BEGIN
            CREATE EXTENSION IF NOT EXISTS vector;
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'pgvector extension not available — skipping (needed for RAG in M5+)';
        END $$;
        """
    )

    # ------------------------------------------------------------------ #
    # firms                                                                #
    # ------------------------------------------------------------------ #
    op.create_table(
        "firms",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_firms_slug", "firms", ["slug"], unique=True)

    # ------------------------------------------------------------------ #
    # users                                                                #
    # ------------------------------------------------------------------ #
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "firm_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("firms.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "rm",
                "analyst",
                "product_team",
                "admin",
                "data_ops",
                name="user_role_enum",
            ),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_firm_id", "users", ["firm_id"])

    # ------------------------------------------------------------------ #
    # trading_calendar                                                     #
    # Every NAV query INNER JOINs this table — no weekend rows ever used. #
    # ------------------------------------------------------------------ #
    op.create_table(
        "trading_calendar",
        sa.Column("date", sa.Date(), primary_key=True),
        sa.Column("is_trading_day", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("source", sa.String(50), nullable=False, server_default="NSE_FO"),
    )

    # ------------------------------------------------------------------ #
    # benchmarks                                                           #
    # ------------------------------------------------------------------ #
    op.create_table(
        "benchmarks",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("index_family", sa.String(100), nullable=True),
        sa.Column("index_type", sa.String(10), nullable=False, server_default="TRI"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # ------------------------------------------------------------------ #
    # schemes (fund master)                                                #
    # ------------------------------------------------------------------ #
    op.create_table(
        "schemes",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("amc_name", sa.String(255), nullable=False),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("subcategory", sa.String(100), nullable=True),
        sa.Column("sebi_category", sa.String(100), nullable=True),
        sa.Column(
            "benchmark_id",
            sa.String(100),
            sa.ForeignKey("benchmarks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("plan_type", sa.String(20), nullable=False, server_default="growth"),
        sa.Column("option_type", sa.String(20), nullable=False, server_default="direct"),
        sa.Column("launch_date", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_schemes_category", "schemes", ["category"])
    op.create_index("ix_schemes_amc_name", "schemes", ["amc_name"])
    op.create_index("ix_schemes_is_active", "schemes", ["is_active"])
    op.create_index("ix_schemes_benchmark_id", "schemes", ["benchmark_id"])

    # ------------------------------------------------------------------ #
    # data_versions                                                        #
    # Append-only promotion log — never deleted.                          #
    # ------------------------------------------------------------------ #
    op.create_table(
        "data_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("as_of_date", sa.DateTime(timezone=False), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "staging",
                "production",
                "archived",
                name="data_version_status_enum",
            ),
            nullable=False,
            server_default="staging",
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "promoted_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_data_versions_status", "data_versions", ["status"])

    # ------------------------------------------------------------------ #
    # nav_raw  (staging)                                                   #
    # ------------------------------------------------------------------ #
    op.create_table(
        "nav_raw",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "scheme_id",
            sa.String(100),
            sa.ForeignKey("schemes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("nav", sa.Numeric(20, 6), nullable=False),
        sa.Column("source_file_id", sa.String(255), nullable=True),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("scheme_id", "date", name="uq_nav_raw_scheme_date"),
    )
    op.create_index("ix_nav_raw_scheme_id", "nav_raw", ["scheme_id"])
    op.create_index("ix_nav_raw_date", "nav_raw", ["date"])

    # ------------------------------------------------------------------ #
    # nav_production  (validated)                                          #
    # ------------------------------------------------------------------ #
    op.create_table(
        "nav_production",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "scheme_id",
            sa.String(100),
            sa.ForeignKey("schemes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("nav", sa.Numeric(20, 6), nullable=False),
        sa.Column(
            "data_version_id",
            sa.Integer(),
            sa.ForeignKey("data_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.UniqueConstraint("scheme_id", "date", name="uq_nav_production_scheme_date"),
    )
    op.create_index("ix_nav_production_scheme_id", "nav_production", ["scheme_id"])
    op.create_index("ix_nav_production_date", "nav_production", ["date"])
    op.create_index("ix_nav_production_data_version_id", "nav_production", ["data_version_id"])

    # ------------------------------------------------------------------ #
    # benchmark_nav_raw  (staging)                                         #
    # ------------------------------------------------------------------ #
    op.create_table(
        "benchmark_nav_raw",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "benchmark_id",
            sa.String(100),
            sa.ForeignKey("benchmarks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(20, 6), nullable=False),
        sa.Column("source_file_id", sa.String(255), nullable=True),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("benchmark_id", "date", name="uq_benchmark_nav_raw_bm_date"),
    )
    op.create_index("ix_benchmark_nav_raw_benchmark_id", "benchmark_nav_raw", ["benchmark_id"])
    op.create_index("ix_benchmark_nav_raw_date", "benchmark_nav_raw", ["date"])

    # ------------------------------------------------------------------ #
    # benchmark_nav_production  (validated)                                #
    # ------------------------------------------------------------------ #
    op.create_table(
        "benchmark_nav_production",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "benchmark_id",
            sa.String(100),
            sa.ForeignKey("benchmarks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(20, 6), nullable=False),
        sa.Column(
            "data_version_id",
            sa.Integer(),
            sa.ForeignKey("data_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "benchmark_id", "date", name="uq_benchmark_nav_production_bm_date"
        ),
    )
    op.create_index(
        "ix_benchmark_nav_production_benchmark_id",
        "benchmark_nav_production",
        ["benchmark_id"],
    )
    op.create_index("ix_benchmark_nav_production_date", "benchmark_nav_production", ["date"])
    op.create_index(
        "ix_benchmark_nav_production_data_version_id",
        "benchmark_nav_production",
        ["data_version_id"],
    )


def downgrade() -> None:
    # Drop in reverse dependency order
    op.drop_table("benchmark_nav_production")
    op.drop_table("benchmark_nav_raw")
    op.drop_table("nav_production")
    op.drop_table("nav_raw")
    op.drop_table("data_versions")
    op.drop_table("schemes")
    op.drop_table("benchmarks")
    op.drop_table("trading_calendar")
    op.drop_table("users")
    op.drop_table("firms")

    # Drop enum types
    op.execute("DROP TYPE IF EXISTS data_version_status_enum")
    op.execute("DROP TYPE IF EXISTS user_role_enum")
