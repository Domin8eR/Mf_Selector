"""Benchmark (market index) master."""

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base


class Benchmark(Base):
    __tablename__ = "benchmark"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)  # e.g. NIFTY50-TRI
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    index_family: Mapped[str | None] = mapped_column(String(100))
    index_type: Mapped[str] = mapped_column(String(10), nullable=False, default="TRI")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    scheme_plans: Mapped[list["SchemePlan"]] = relationship(  # type: ignore[name-defined]
        "SchemePlan", back_populates="benchmark"
    )
    nav_daily: Mapped[list["BenchmarkLevelDaily"]] = relationship(  # type: ignore[name-defined]
        "BenchmarkLevelDaily", back_populates="benchmark"
    )
