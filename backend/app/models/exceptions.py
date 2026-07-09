"""Data quality exception model."""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class ExceptionSeverity(str, enum.Enum):
    BLOCKING = "blocking"
    WARNING = "warning"
    INFO = "info"


class ExceptionStatus(str, enum.Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class DataQualityException(Base):
    """One data quality issue raised during validation or ingestion."""

    __tablename__ = "data_quality_exception"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    domain: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    severity: Mapped[ExceptionSeverity] = mapped_column(
        Enum(ExceptionSeverity, name="exception_severity"),
        nullable=False,
        index=True,
    )
    status: Mapped[ExceptionStatus] = mapped_column(
        Enum(ExceptionStatus, name="exception_status"),
        nullable=False,
        default=ExceptionStatus.OPEN,
        index=True,
    )
    scheme_plan_id: Mapped[str | None] = mapped_column(String(100))
    benchmark_id: Mapped[str | None] = mapped_column(String(100))
    affected_date: Mapped[str | None] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    ingestion_run_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
