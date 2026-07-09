"""Scheme and SchemePlan models.

SchemePlan is the rankable entity — one row per plan/option combination
(e.g. HDFC Large Cap Direct-Growth).  Scheme is the parent fund concept.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base


class Scheme(Base):
    """Parent fund, independent of plan/option."""

    __tablename__ = "scheme"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    amc_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("amc.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    amc: Mapped["AMC"] = relationship("AMC", back_populates="schemes")  # type: ignore[name-defined]
    plans: Mapped[list["SchemePlan"]] = relationship("SchemePlan", back_populates="scheme")


class SchemePlan(Base):
    """
    The rankable entity.  One row per (scheme × plan_type × option_type).
    Rankings, metrics and NAV series all reference scheme_plan_id.
    Only Direct-Growth plans are included in ranking runs.
    """

    __tablename__ = "scheme_plan"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    scheme_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("scheme.id"), nullable=False, index=True
    )
    category_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("category.id"), nullable=False, index=True
    )
    benchmark_id: Mapped[str | None] = mapped_column(
        String(100), ForeignKey("benchmark.id"), index=True
    )
    plan_type: Mapped[str] = mapped_column(String(20), nullable=False, default="growth")
    option_type: Mapped[str] = mapped_column(String(20), nullable=False, default="direct")
    amfi_code: Mapped[str | None] = mapped_column(String(20))
    isin: Mapped[str | None] = mapped_column(String(20))
    launch_date: Mapped[date | None] = mapped_column(Date)
    aum_cr: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    expense_ratio_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    scheme: Mapped["Scheme"] = relationship("Scheme", back_populates="plans")
    category: Mapped["Category"] = relationship(  # type: ignore[name-defined]
        "Category", back_populates="scheme_plans"
    )
    benchmark: Mapped["Benchmark | None"] = relationship(  # type: ignore[name-defined]
        "Benchmark", back_populates="scheme_plans"
    )
    nav_daily: Mapped[list["FundNavDaily"]] = relationship(  # type: ignore[name-defined]
        "FundNavDaily", back_populates="scheme_plan"
    )
    metric_snapshots: Mapped[list["MetricValueSnapshot"]] = relationship(  # type: ignore[name-defined]
        "MetricValueSnapshot", back_populates="scheme_plan"
    )
    rolling_metrics: Mapped[list["RollingMetricValue"]] = relationship(  # type: ignore[name-defined]
        "RollingMetricValue", back_populates="scheme_plan"
    )
    ranking_results: Mapped[list["RankingResult"]] = relationship(  # type: ignore[name-defined]
        "RankingResult", back_populates="scheme_plan"
    )
