"""Chat thread, message, and AI tool call log models."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger, DateTime, ForeignKey, Integer, SmallInteger,
    String, Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base


class ChatThread(Base):
    __tablename__ = "chat_thread"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    messages: Mapped[list["ChatMessage"]] = relationship(
        "ChatMessage",
        back_populates="thread",
        order_by="ChatMessage.created_at",
        foreign_keys="[ChatMessage.thread_id]",
    )


class ChatMessage(Base):
    __tablename__ = "chat_message"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_thread.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sources: Mapped[list | None] = mapped_column(JSONB)
    intent: Mapped[str | None] = mapped_column(String(100))
    confidence: Mapped[str | None] = mapped_column(String(20))

    result_component_type: Mapped[str | None] = mapped_column(String(40))
    table_columns: Mapped[list | None] = mapped_column(JSONB)
    table_rows: Mapped[list | None] = mapped_column(JSONB)
    chart_type: Mapped[str | None] = mapped_column(String(40))
    chart_data: Mapped[list | None] = mapped_column(JSONB)
    source_tables: Mapped[list | None] = mapped_column(JSONB)
    data_confidence: Mapped[dict | None] = mapped_column(JSONB)
    suggested_next_actions: Mapped[list | None] = mapped_column(JSONB)
    feedback_score: Mapped[int | None] = mapped_column(SmallInteger)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    thread: Mapped["ChatThread"] = relationship(
        "ChatThread",
        back_populates="messages",
        foreign_keys=[thread_id],
    )
    tool_calls: Mapped[list["ToolCallLog"]] = relationship(
        "ToolCallLog",
        back_populates="message",
        foreign_keys="[ToolCallLog.message_id]",
    )


class ToolCallLog(Base):
    __tablename__ = "tool_call_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    message_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("chat_message.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    thread_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_thread.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    input_json: Mapped[dict | None] = mapped_column(JSONB)
    output_json: Mapped[dict | None] = mapped_column(JSONB)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ok")
    error_detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    message: Mapped["ChatMessage | None"] = relationship(
        "ChatMessage",
        back_populates="tool_calls",
        foreign_keys=[message_id],
    )
