"""Comparison session model — stores fund-comparison history and saved comparisons."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class ComparisonSession(Base):
    __tablename__ = "comparison_session"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    fund_ids: Mapped[list] = mapped_column(JSONB, nullable=False)
    label: Mapped[str | None] = mapped_column(String(200))
    is_saved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
