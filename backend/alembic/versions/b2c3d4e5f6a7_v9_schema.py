"""v9 schema — replaces M2 NAV tables with full v9 design.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2024-11-21 00:00:00.000000

Changes:
  DROP: benchmarks, schemes, data_versions, nav_raw, nav_production,
        benchmark_nav_raw, benchmark_nav_production  (M2 names)
  CREATE (v9):
    amc, category, benchmark, scheme, scheme_plan,
    data_version, ingestion_run,
    fund_nav_daily, benchmark_level_daily,
    fund_return_daily, benchmark_return_daily, excess_return_daily,
    metric_definition, metric_value_snapshot, rolling_metric_value, calculation_lineage,
    rule_set, rule_version, rule_component,
    ranking_run, ranking_result, ranking_component_contribution
  KEEP: firms, users, trading_calendar (unchanged)
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # Drop M2 tables that are being replaced (order: FK-safe)             #
    # ------------------------------------------------------------------ #
    for tbl in (
        "benchmark_nav_production",
        "benchmark_nav_raw",
        "nav_production",
        "nav_raw",
        "data_versions",
        "schemes",
        "benchmarks",
    ):
        op.execute(f"DROP TABLE IF EXISTS {tbl} CASCADE")

    # Drop M2 enums
    op.execute("DROP TYPE IF EXISTS data_version_status_enum")

    # ------------------------------------------------------------------ #
    # amc                                                                  #
    # ------------------------------------------------------------------ #
    op.create_table(
        "amc",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("short_name", sa.String(50)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # ------------------------------------------------------------------ #
    # category                                                             #
    # ------------------------------------------------------------------ #
    op.create_table(
        "category",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("sebi_name", sa.String(200)),
        sa.Column("asset_class", sa.String(50), nullable=False, server_default="equity"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # ------------------------------------------------------------------ #
    # benchmark                                                            #
    # ------------------------------------------------------------------ #
    op.create_table(
        "benchmark",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("index_family", sa.String(100)),
        sa.Column("index_type", sa.String(10), nullable=False, server_default="TRI"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # ------------------------------------------------------------------ #
    # scheme                                                               #
    # ------------------------------------------------------------------ #
    op.create_table(
        "scheme",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("amc_id", sa.String(100), sa.ForeignKey("amc.id"), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_scheme_amc_id", "scheme", ["amc_id"])

    # ------------------------------------------------------------------ #
    # scheme_plan  (the rankable entity)                                   #
    # ------------------------------------------------------------------ #
    op.create_table(
        "scheme_plan",
        sa.Column("id", sa.String(100), primary_key=True),   # e.g. HDFC-LC-D-G
        sa.Column("scheme_id", sa.String(100), sa.ForeignKey("scheme.id"), nullable=False),
        sa.Column("category_id", sa.String(100), sa.ForeignKey("category.id"), nullable=False),
        sa.Column("benchmark_id", sa.String(100), sa.ForeignKey("benchmark.id")),
        sa.Column("plan_type", sa.String(20), nullable=False, server_default="growth"),
        sa.Column("option_type", sa.String(20), nullable=False, server_default="direct"),
        sa.Column("amfi_code", sa.String(20)),
        sa.Column("isin", sa.String(20)),
        sa.Column("launch_date", sa.Date()),
        sa.Column("aum_cr", sa.Numeric(20, 2)),
        sa.Column("expense_ratio_pct", sa.Numeric(6, 4)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_scheme_plan_scheme_id", "scheme_plan", ["scheme_id"])
    op.create_index("ix_scheme_plan_category_id", "scheme_plan", ["category_id"])
    op.create_index("ix_scheme_plan_benchmark_id", "scheme_plan", ["benchmark_id"])
    op.create_index("ix_scheme_plan_is_active", "scheme_plan", ["is_active"])

    # ------------------------------------------------------------------ #
    # data_version                                                         #
    # ------------------------------------------------------------------ #
    op.create_table(
        "data_version",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("as_of_date", sa.Date()),
        sa.Column(
            "status",
            sa.Enum("staging", "production", "archived", name="data_version_status"),
            nullable=False,
            server_default="staging",
        ),
        sa.Column("notes", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("promoted_at", sa.DateTime(timezone=True)),
        sa.Column(
            "promoted_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
    )
    op.create_index("ix_data_version_status", "data_version", ["status"])
    op.create_index("ix_data_version_as_of_date", "data_version", ["as_of_date"])

    # ------------------------------------------------------------------ #
    # ingestion_run                                                        #
    # ------------------------------------------------------------------ #
    op.create_table(
        "ingestion_run",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column(
            "status",
            sa.Enum("running", "completed", "failed", name="ingestion_run_status"),
            nullable=False,
            server_default="running",
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("rows_ingested", sa.Integer(), server_default="0"),
        sa.Column("rows_failed", sa.Integer(), server_default="0"),
        sa.Column("error_message", sa.Text()),
    )

    # ------------------------------------------------------------------ #
    # fund_nav_daily  (production NAVs, validated)                        #
    # ------------------------------------------------------------------ #
    op.create_table(
        "fund_nav_daily",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "scheme_plan_id",
            sa.String(100),
            sa.ForeignKey("scheme_plan.id"),
            nullable=False,
        ),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("nav", sa.Numeric(20, 6), nullable=False),
        sa.Column("data_version_id", sa.Integer(), sa.ForeignKey("data_version.id"), nullable=False),
        sa.UniqueConstraint("scheme_plan_id", "date", name="uq_fund_nav_daily"),
    )
    op.create_index("ix_fund_nav_daily_sp_id", "fund_nav_daily", ["scheme_plan_id"])
    op.create_index("ix_fund_nav_daily_date", "fund_nav_daily", ["date"])

    # ------------------------------------------------------------------ #
    # benchmark_level_daily                                                #
    # ------------------------------------------------------------------ #
    op.create_table(
        "benchmark_level_daily",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "benchmark_id",
            sa.String(100),
            sa.ForeignKey("benchmark.id"),
            nullable=False,
        ),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(20, 6), nullable=False),
        sa.Column("data_version_id", sa.Integer(), sa.ForeignKey("data_version.id"), nullable=False),
        sa.UniqueConstraint("benchmark_id", "date", name="uq_benchmark_level_daily"),
    )
    op.create_index("ix_benchmark_level_daily_bm_id", "benchmark_level_daily", ["benchmark_id"])
    op.create_index("ix_benchmark_level_daily_date", "benchmark_level_daily", ["date"])

    # ------------------------------------------------------------------ #
    # fund_return_daily  (computed, pre-stored for speed)                 #
    # ------------------------------------------------------------------ #
    op.create_table(
        "fund_return_daily",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "scheme_plan_id",
            sa.String(100),
            sa.ForeignKey("scheme_plan.id"),
            nullable=False,
        ),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("daily_return", sa.Numeric(20, 10), nullable=False),
        sa.UniqueConstraint("scheme_plan_id", "date", name="uq_fund_return_daily"),
    )
    op.create_index("ix_fund_return_daily_sp_id", "fund_return_daily", ["scheme_plan_id"])

    # ------------------------------------------------------------------ #
    # benchmark_return_daily                                               #
    # ------------------------------------------------------------------ #
    op.create_table(
        "benchmark_return_daily",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "benchmark_id",
            sa.String(100),
            sa.ForeignKey("benchmark.id"),
            nullable=False,
        ),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("daily_return", sa.Numeric(20, 10), nullable=False),
        sa.UniqueConstraint("benchmark_id", "date", name="uq_benchmark_return_daily"),
    )
    op.create_index("ix_benchmark_return_daily_bm_id", "benchmark_return_daily", ["benchmark_id"])

    # ------------------------------------------------------------------ #
    # excess_return_daily                                                  #
    # ------------------------------------------------------------------ #
    op.create_table(
        "excess_return_daily",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "scheme_plan_id",
            sa.String(100),
            sa.ForeignKey("scheme_plan.id"),
            nullable=False,
        ),
        sa.Column(
            "benchmark_id",
            sa.String(100),
            sa.ForeignKey("benchmark.id"),
            nullable=False,
        ),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("excess_return", sa.Numeric(20, 10), nullable=False),
        sa.UniqueConstraint(
            "scheme_plan_id", "benchmark_id", "date", name="uq_excess_return_daily"
        ),
    )
    op.create_index("ix_excess_return_daily_sp_id", "excess_return_daily", ["scheme_plan_id"])

    # ------------------------------------------------------------------ #
    # metric_definition                                                    #
    # ------------------------------------------------------------------ #
    op.create_table(
        "metric_definition",
        sa.Column("id", sa.String(100), primary_key=True),   # e.g. IR_1Y, IR_SLOPE_2Y
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("formula_description", sa.Text()),
        sa.Column("direction", sa.String(20), nullable=False, server_default="higher_better"),
        sa.Column("unit", sa.String(20)),
        sa.Column("window_years", sa.Integer()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # ------------------------------------------------------------------ #
    # metric_value_snapshot  (evaluation-date point-in-time metric values) #
    # ------------------------------------------------------------------ #
    op.create_table(
        "metric_value_snapshot",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "scheme_plan_id",
            sa.String(100),
            sa.ForeignKey("scheme_plan.id"),
            nullable=False,
        ),
        sa.Column(
            "metric_id",
            sa.String(100),
            sa.ForeignKey("metric_definition.id"),
            nullable=False,
        ),
        sa.Column("evaluation_date", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(20, 8)),
        sa.Column("status", sa.String(30), nullable=False, server_default="ok"),
        sa.Column("confidence", sa.String(10), nullable=False, server_default="high"),
        sa.Column("observation_count", sa.Integer()),
        sa.Column("window_start_date", sa.Date()),
        sa.Column("window_end_date", sa.Date()),
        sa.Column("calculation_version", sa.String(50), nullable=False, server_default="1.0"),
        sa.Column("data_version_id", sa.Integer(), sa.ForeignKey("data_version.id"), nullable=False),
        sa.UniqueConstraint(
            "scheme_plan_id", "metric_id", "evaluation_date",
            name="uq_metric_value_snapshot",
        ),
    )
    op.create_index("ix_mvs_sp_id", "metric_value_snapshot", ["scheme_plan_id"])
    op.create_index("ix_mvs_eval_date", "metric_value_snapshot", ["evaluation_date"])
    op.create_index("ix_mvs_metric_id", "metric_value_snapshot", ["metric_id"])

    # ------------------------------------------------------------------ #
    # rolling_metric_value  (monthly rolling series for charts)           #
    # ------------------------------------------------------------------ #
    op.create_table(
        "rolling_metric_value",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "scheme_plan_id",
            sa.String(100),
            sa.ForeignKey("scheme_plan.id"),
            nullable=False,
        ),
        sa.Column(
            "metric_id",
            sa.String(100),
            sa.ForeignKey("metric_definition.id"),
            nullable=False,
        ),
        sa.Column("evaluation_date", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(20, 8)),
        sa.Column("window_start_date", sa.Date()),
        sa.Column("window_end_date", sa.Date()),
        sa.Column("observation_count", sa.Integer()),
        sa.Column("calculation_version", sa.String(50), nullable=False, server_default="1.0"),
        sa.UniqueConstraint(
            "scheme_plan_id", "metric_id", "evaluation_date",
            name="uq_rolling_metric_value",
        ),
    )
    op.create_index("ix_rmv_sp_id", "rolling_metric_value", ["scheme_plan_id"])
    op.create_index("ix_rmv_metric_id", "rolling_metric_value", ["metric_id"])
    op.create_index("ix_rmv_eval_date", "rolling_metric_value", ["evaluation_date"])

    # ------------------------------------------------------------------ #
    # calculation_lineage                                                  #
    # ------------------------------------------------------------------ #
    op.create_table(
        "calculation_lineage",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.String(200), nullable=False),
        sa.Column("metric_id", sa.String(100), sa.ForeignKey("metric_definition.id")),
        sa.Column("evaluation_date", sa.Date()),
        sa.Column("data_version_id", sa.Integer(), sa.ForeignKey("data_version.id")),
        sa.Column("calculation_version", sa.String(50)),
        sa.Column("inputs_summary", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # ------------------------------------------------------------------ #
    # rule_set                                                             #
    # ------------------------------------------------------------------ #
    op.create_table(
        "rule_set",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("category_id", sa.String(100), sa.ForeignKey("category.id")),
        sa.Column("active_version_id", sa.String(100)),  # FK added after rule_version
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # ------------------------------------------------------------------ #
    # rule_version  (immutable, append-only history)                      #
    # ------------------------------------------------------------------ #
    op.create_table(
        "rule_version",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("rule_set_id", sa.String(100), sa.ForeignKey("rule_set.id"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("draft", "submitted", "approved", "active", "archived", name="rule_version_status"),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("submitted_by_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("approved_by_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("approval_rationale", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_rule_version_rule_set_id", "rule_version", ["rule_set_id"])
    op.create_index("ix_rule_version_status", "rule_version", ["status"])

    # Add FK from rule_set.active_version_id → rule_version.id
    op.create_foreign_key(
        "fk_rule_set_active_version",
        "rule_set",
        "rule_version",
        ["active_version_id"],
        ["id"],
    )

    # ------------------------------------------------------------------ #
    # rule_component                                                       #
    # ------------------------------------------------------------------ #
    op.create_table(
        "rule_component",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column(
            "rule_version_id",
            sa.String(100),
            sa.ForeignKey("rule_version.id"),
            nullable=False,
        ),
        sa.Column("metric_id", sa.String(100), sa.ForeignKey("metric_definition.id"), nullable=False),
        sa.Column("weight", sa.Numeric(5, 4), nullable=False),     # e.g. 0.3000 = 30%
        sa.Column("direction", sa.String(20), nullable=False, server_default="higher_better"),
        sa.Column("normalization", sa.String(30), nullable=False, server_default="percentile_rank"),
        sa.Column("window_years", sa.Integer()),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_rule_component_rv_id", "rule_component", ["rule_version_id"])

    # ------------------------------------------------------------------ #
    # ranking_run                                                          #
    # ------------------------------------------------------------------ #
    op.create_table(
        "ranking_run",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("rule_version_id", sa.String(100), sa.ForeignKey("rule_version.id"), nullable=False),
        sa.Column("category_id", sa.String(100), sa.ForeignKey("category.id"), nullable=False),
        sa.Column("evaluation_date", sa.Date(), nullable=False),
        sa.Column("data_version_id", sa.Integer(), sa.ForeignKey("data_version.id"), nullable=False),
        sa.Column("calculation_version", sa.String(50), nullable=False, server_default="1.0"),
        sa.Column("scheme_count", sa.Integer()),
        sa.Column(
            "run_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_ranking_run_category_id", "ranking_run", ["category_id"])
    op.create_index("ix_ranking_run_eval_date", "ranking_run", ["evaluation_date"])

    # ------------------------------------------------------------------ #
    # ranking_result                                                       #
    # ------------------------------------------------------------------ #
    op.create_table(
        "ranking_result",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("ranking_run_id", sa.String(100), sa.ForeignKey("ranking_run.id"), nullable=False),
        sa.Column(
            "scheme_plan_id",
            sa.String(100),
            sa.ForeignKey("scheme_plan.id"),
            nullable=False,
        ),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("score", sa.Numeric(10, 4), nullable=False),
        sa.Column("prev_rank", sa.Integer()),      # rank from prior evaluation_date
        sa.Column("rank_change", sa.Integer()),    # negative = improved
        sa.Column("status_label", sa.String(30)),  # Strong / Good / Neutral / Watch / Weak
        sa.UniqueConstraint("ranking_run_id", "scheme_plan_id", name="uq_ranking_result"),
    )
    op.create_index("ix_ranking_result_run_id", "ranking_result", ["ranking_run_id"])

    # ------------------------------------------------------------------ #
    # ranking_component_contribution                                       #
    # ------------------------------------------------------------------ #
    op.create_table(
        "ranking_component_contribution",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "ranking_result_id",
            sa.BigInteger(),
            sa.ForeignKey("ranking_result.id"),
            nullable=False,
        ),
        sa.Column("metric_id", sa.String(100), sa.ForeignKey("metric_definition.id"), nullable=False),
        sa.Column("raw_value", sa.Numeric(20, 8)),
        sa.Column("normalized_value", sa.Numeric(10, 4)),
        sa.Column("weight", sa.Numeric(5, 4)),
        sa.Column("contribution", sa.Numeric(10, 4)),
    )
    op.create_index(
        "ix_rcc_result_id", "ranking_component_contribution", ["ranking_result_id"]
    )


def downgrade() -> None:
    for tbl in (
        "ranking_component_contribution",
        "ranking_result",
        "ranking_run",
        "rule_component",
    ):
        op.drop_table(tbl)

    op.drop_constraint("fk_rule_set_active_version", "rule_set", type_="foreignkey")
    op.drop_table("rule_version")
    op.drop_table("rule_set")
    op.drop_table("calculation_lineage")
    op.drop_table("rolling_metric_value")
    op.drop_table("metric_value_snapshot")
    op.drop_table("metric_definition")
    op.drop_table("excess_return_daily")
    op.drop_table("benchmark_return_daily")
    op.drop_table("fund_return_daily")
    op.drop_table("benchmark_level_daily")
    op.drop_table("fund_nav_daily")
    op.drop_table("ingestion_run")
    op.drop_table("data_version")
    op.drop_table("scheme_plan")
    op.drop_table("scheme")
    op.drop_table("benchmark")
    op.drop_table("category")
    op.drop_table("amc")

    op.execute("DROP TYPE IF EXISTS rule_version_status")
    op.execute("DROP TYPE IF EXISTS ingestion_run_status")
    op.execute("DROP TYPE IF EXISTS data_version_status")
