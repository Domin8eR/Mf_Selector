"""Time-series NAV and daily return tables (v9 schema)."""

from datetime import date
from decimal import Decimal

from sqlalchemy import BigInteger, Date, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base


class FundNavDaily(Base):
    """Production (validated) daily NAV for each scheme plan."""

    __tablename__ = "fund_nav_daily"
    __table_args__ = (
        UniqueConstraint("scheme_plan_id", "date", name="uq_fund_nav_daily"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    scheme_plan_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("scheme_plan.id"), nullable=False, index=True
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    nav: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    data_version_id: Mapped[int] = mapped_column(
        ForeignKey("data_version.id"), nullable=False, index=True
    )

    scheme_plan: Mapped["SchemePlan"] = relationship(  # type: ignore[name-defined]
        "SchemePlan", back_populates="nav_daily"
    )


class BenchmarkLevelDaily(Base):
    """Production daily benchmark index values (TRI)."""

    __tablename__ = "benchmark_level_daily"
    __table_args__ = (
        UniqueConstraint("benchmark_id", "date", name="uq_benchmark_level_daily"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    benchmark_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("benchmark.id"), nullable=False, index=True
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    value: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    data_version_id: Mapped[int] = mapped_column(
        ForeignKey("data_version.id"), nullable=False
    )

    benchmark: Mapped["Benchmark"] = relationship(  # type: ignore[name-defined]
        "Benchmark", back_populates="nav_daily"
    )


class FundReturnDaily(Base):
    """Pre-computed daily fund returns: r_f,t = NAV_t / NAV_t-1 - 1."""

    __tablename__ = "fund_return_daily"
    __table_args__ = (
        UniqueConstraint("scheme_plan_id", "date", name="uq_fund_return_daily"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    scheme_plan_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("scheme_plan.id"), nullable=False, index=True
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    daily_return: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)


class BenchmarkReturnDaily(Base):
    """Pre-computed daily benchmark returns."""

    __tablename__ = "benchmark_return_daily"
    __table_args__ = (
        UniqueConstraint("benchmark_id", "date", name="uq_benchmark_return_daily"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    benchmark_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("benchmark.id"), nullable=False, index=True
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    daily_return: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)


class ExcessReturnDaily(Base):
    """Pre-computed excess returns: e_t = r_f,t - r_b,t (trading days only)."""

    __tablename__ = "excess_return_daily"
    __table_args__ = (
        UniqueConstraint(
            "scheme_plan_id", "benchmark_id", "date",
            name="uq_excess_return_daily",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    scheme_plan_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("scheme_plan.id"), nullable=False, index=True
    )
    benchmark_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("benchmark.id"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    excess_return: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
