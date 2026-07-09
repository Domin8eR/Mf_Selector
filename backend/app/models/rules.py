"""Rule set, version, component, and governance models."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base


class RuleVersionStatus(str, enum.Enum):
    draft = "draft"
    submitted = "submitted"
    approved = "approved"
    active = "active"
    archived = "archived"


class RuleSet(Base):
    """
    Collection of rule versions for a category.
    active_version_id points to the currently live RuleVersion.
    """

    __tablename__ = "rule_set"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category_id: Mapped[str | None] = mapped_column(
        String(100), ForeignKey("category.id")
    )
    active_version_id: Mapped[str | None] = mapped_column(
        String(100), ForeignKey("rule_version.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    category: Mapped["Category | None"] = relationship(  # type: ignore[name-defined]
        "Category", back_populates="rule_sets"
    )
    versions: Mapped[list["RuleVersion"]] = relationship(
        "RuleVersion",
        back_populates="rule_set",
        foreign_keys="RuleVersion.rule_set_id",
    )


class RuleVersion(Base):
    """
    Immutable snapshot of a rule set.  Append-only — never deleted.
    Only the rule_set.active_version_id pointer moves.
    """

    __tablename__ = "rule_version"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    rule_set_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("rule_set.id"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[RuleVersionStatus] = mapped_column(
        Enum(RuleVersionStatus, name="rule_version_status"),
        nullable=False,
        default=RuleVersionStatus.draft,
        index=True,
    )
    submitted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    approval_rationale: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    rule_set: Mapped["RuleSet"] = relationship(
        "RuleSet",
        back_populates="versions",
        foreign_keys=[rule_set_id],
    )
    components: Mapped[list["RuleComponent"]] = relationship(
        "RuleComponent", back_populates="rule_version", order_by="RuleComponent.display_order"
    )


class RuleComponent(Base):
    """One metric + weight row within a rule version."""

    __tablename__ = "rule_component"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    rule_version_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("rule_version.id"), nullable=False, index=True
    )
    metric_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("metric_definition.id"), nullable=False
    )
    weight: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    direction: Mapped[str] = mapped_column(
        String(20), nullable=False, default="higher_better"
    )
    normalization: Mapped[str] = mapped_column(
        String(30), nullable=False, default="percentile_rank"
    )
    window_years: Mapped[int | None] = mapped_column(Integer)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    rule_version: Mapped["RuleVersion"] = relationship(
        "RuleVersion", back_populates="components"
    )
    metric: Mapped["MetricDefinition"] = relationship(  # type: ignore[name-defined]
        "MetricDefinition"
    )
