"""Ranking run, result, and component contribution models."""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base


class RankingRun(Base):
    """Metadata for one ranking execution (category + date + rule version)."""

    __tablename__ = "ranking_run"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    rule_version_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("rule_version.id"), nullable=False
    )
    category_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("category.id"), nullable=False, index=True
    )
    evaluation_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    data_version_id: Mapped[int] = mapped_column(
        ForeignKey("data_version.id"), nullable=False
    )
    calculation_version: Mapped[str] = mapped_column(
        String(50), nullable=False, default="1.0"
    )
    scheme_count: Mapped[int | None] = mapped_column(Integer)
    run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    category: Mapped["Category"] = relationship(  # type: ignore[name-defined]
        "Category", back_populates="ranking_runs"
    )
    results: Mapped[list["RankingResult"]] = relationship(
        "RankingResult", back_populates="ranking_run", order_by="RankingResult.rank"
    )


class RankingResult(Base):
    """One fund's rank and score within a ranking run."""

    __tablename__ = "ranking_result"
    __table_args__ = (
        UniqueConstraint(
            "ranking_run_id", "scheme_plan_id", name="uq_ranking_result"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ranking_run_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("ranking_run.id"), nullable=False, index=True
    )
    scheme_plan_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("scheme_plan.id"), nullable=False
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    prev_rank: Mapped[int | None] = mapped_column(Integer)
    rank_change: Mapped[int | None] = mapped_column(Integer)
    status_label: Mapped[str | None] = mapped_column(String(30))

    ranking_run: Mapped["RankingRun"] = relationship(
        "RankingRun", back_populates="results"
    )
    scheme_plan: Mapped["SchemePlan"] = relationship(  # type: ignore[name-defined]
        "SchemePlan", back_populates="ranking_results"
    )
    contributions: Mapped[list["RankingComponentContribution"]] = relationship(
        "RankingComponentContribution", back_populates="ranking_result"
    )


class RankingComponentContribution(Base):
    """Per-metric score contribution for a ranking result (explain-rank waterfall)."""

    __tablename__ = "ranking_component_contribution"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ranking_result_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ranking_result.id"), nullable=False, index=True
    )
    metric_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("metric_definition.id"), nullable=False
    )
    raw_value: Mapped[float | None] = mapped_column(Numeric(20, 8))
    normalized_value: Mapped[float | None] = mapped_column(Numeric(10, 4))
    weight: Mapped[float | None] = mapped_column(Numeric(5, 4))
    contribution: Mapped[float | None] = mapped_column(Numeric(10, 4))

    ranking_result: Mapped["RankingResult"] = relationship(
        "RankingResult", back_populates="contributions"
    )
