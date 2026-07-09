from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base


class Scheme(Base):
    """
    Mutual fund scheme master.

    Rules:
    - Only Growth plan / Direct option series are used for metric calculations.
    - Regular and IDCW series are stored but excluded from ranking queries.
    - benchmark_id must point to a TRI benchmark for excess-return calculations.
    """

    __tablename__ = "schemes"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)  # AMFI scheme code
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    amc_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    subcategory: Mapped[str | None] = mapped_column(String(100))
    sebi_category: Mapped[str | None] = mapped_column(String(100))   # official SEBI classification
    benchmark_id: Mapped[str | None] = mapped_column(
        String(100), ForeignKey("benchmarks.id"), index=True
    )
    plan_type: Mapped[str] = mapped_column(String(20), nullable=False, default="growth")
    option_type: Mapped[str] = mapped_column(String(20), nullable=False, default="direct")
    launch_date: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    benchmark: Mapped["Benchmark | None"] = relationship("Benchmark", back_populates="schemes")  # type: ignore[name-defined]
    nav_raw: Mapped[list["NavRaw"]] = relationship("NavRaw", back_populates="scheme")  # type: ignore[name-defined]
    nav_production: Mapped[list["NavProduction"]] = relationship("NavProduction", back_populates="scheme")  # type: ignore[name-defined]
