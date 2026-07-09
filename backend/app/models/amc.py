"""AMC (Asset Management Company) master."""

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base


class AMC(Base):
    __tablename__ = "amc"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    schemes: Mapped[list["Scheme"]] = relationship("Scheme", back_populates="amc")  # type: ignore[name-defined]
