"""Metric definition, point-in-time snapshots, and rolling series."""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base


class MetricDefinition(Base):
    """Registry of all metric formulas (IR_1Y, IR_SLOPE_2Y, OPR_3Y …)."""

    __tablename__ = "metric_definition"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    formula_description: Mapped[str | None] = mapped_column(Text)
    direction: Mapped[str] = mapped_column(
        String(20), nullable=False, default="higher_better"
    )
    unit: Mapped[str | None] = mapped_column(String(20))
    window_years: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )


class MetricValueSnapshot(Base):
    """
    Point-in-time metric value for a scheme plan at an evaluation date.
    One row per (scheme_plan_id, metric_id, evaluation_date).
    """

    __tablename__ = "metric_value_snapshot"
    __table_args__ = (
        UniqueConstraint(
            "scheme_plan_id", "metric_id", "evaluation_date",
            name="uq_metric_value_snapshot",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    scheme_plan_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("scheme_plan.id"), nullable=False, index=True
    )
    metric_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("metric_definition.id"), nullable=False, index=True
    )
    evaluation_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    value: Mapped[float | None] = mapped_column(Numeric(20, 8))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="ok")
    confidence: Mapped[str] = mapped_column(String(10), nullable=False, default="high")
    observation_count: Mapped[int | None] = mapped_column(Integer)
    window_start_date: Mapped[date | None] = mapped_column(Date)
    window_end_date: Mapped[date | None] = mapped_column(Date)
    calculation_version: Mapped[str] = mapped_column(
        String(50), nullable=False, default="1.0"
    )
    data_version_id: Mapped[int] = mapped_column(
        ForeignKey("data_version.id"), nullable=False
    )

    scheme_plan: Mapped["SchemePlan"] = relationship(  # type: ignore[name-defined]
        "SchemePlan", back_populates="metric_snapshots"
    )
    metric: Mapped["MetricDefinition"] = relationship("MetricDefinition")


class RollingMetricValue(Base):
    """
    Monthly rolling metric series used for charts (e.g. rolling 3Y IR over time).
    One row per (scheme_plan_id, metric_id, evaluation_date).
    """

    __tablename__ = "rolling_metric_value"
    __table_args__ = (
        UniqueConstraint(
            "scheme_plan_id", "metric_id", "evaluation_date",
            name="uq_rolling_metric_value",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    scheme_plan_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("scheme_plan.id"), nullable=False, index=True
    )
    metric_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("metric_definition.id"), nullable=False, index=True
    )
    evaluation_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    value: Mapped[float | None] = mapped_column(Numeric(20, 8))
    window_start_date: Mapped[date | None] = mapped_column(Date)
    window_end_date: Mapped[date | None] = mapped_column(Date)
    observation_count: Mapped[int | None] = mapped_column(Integer)
    calculation_version: Mapped[str] = mapped_column(
        String(50), nullable=False, default="1.0"
    )

    scheme_plan: Mapped["SchemePlan"] = relationship(  # type: ignore[name-defined]
        "SchemePlan", back_populates="rolling_metrics"
    )
