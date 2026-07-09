"""Fund category master (e.g. Large Cap, Mid Cap)."""

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base


class Category(Base):
    __tablename__ = "category"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)  # e.g. LARGE_CAP
    name: Mapped[str] = mapped_column(String(100), nullable=False)   # e.g. Large Cap
    sebi_name: Mapped[str | None] = mapped_column(String(200))
    asset_class: Mapped[str] = mapped_column(String(50), nullable=False, default="equity")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    scheme_plans: Mapped[list["SchemePlan"]] = relationship("SchemePlan", back_populates="category")  # type: ignore[name-defined]
    rule_sets: Mapped[list["RuleSet"]] = relationship("RuleSet", back_populates="category")  # type: ignore[name-defined]
    ranking_runs: Mapped[list["RankingRun"]] = relationship("RankingRun", back_populates="category")  # type: ignore[name-defined]
