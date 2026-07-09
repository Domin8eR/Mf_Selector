"""Data version and ingestion run tracking (v9 schema)."""

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class DataVersionStatus(str, enum.Enum):
    """Lifecycle stages for a data promotion batch."""

    STAGING = "staging"
    PRODUCTION = "production"
    ARCHIVED = "archived"


class IngestionRunStatus(str, enum.Enum):
    """Execution states for one ingestion pipeline run."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class DataVersion(Base):
    """
    Append-only promotion log.
    Every fund_nav_daily / metric_value_snapshot row references this.
    Only status and promoted_at are mutated after creation.
    """

    __tablename__ = "data_version"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    as_of_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[DataVersionStatus] = mapped_column(
        Enum(DataVersionStatus, name="data_version_status"),
        nullable=False,
        default=DataVersionStatus.STAGING,
        index=True,
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    promoted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


class IngestionRun(Base):
    """One row per ingestion pipeline execution."""

    __tablename__ = "ingestion_run"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[IngestionRunStatus] = mapped_column(
        Enum(IngestionRunStatus, name="ingestion_run_status"),
        nullable=False,
        default=IngestionRunStatus.RUNNING,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rows_ingested: Mapped[int] = mapped_column(Integer, default=0)
    rows_failed: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
