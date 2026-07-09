"""Research Chat endpoint — POST /chat/query, GET /chat/threads, PATCH /chat/messages/{id}/feedback."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, select, text, update
from sqlalchemy.orm import Session

from app.ai.supervisor import classify_intent, generate_response
from app.ai.tools import call_tool
from app.core.db import get_db
from app.models.chat import ChatMessage, ChatThread, ToolCallLog

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatQuery(BaseModel):
    message: str
    thread_id: str | None = None
    # context from Fund Detail or Compare page
    context: dict | None = None


class DataConfidence(BaseModel):
    level: str  # "high" | "medium" | "low"
    coverage: float
    recency: str


class ChatResponse(BaseModel):
    thread_id: str
    message_id: int
    answer: str
    intent: str
    tool_calls: list[dict]
    sources: list[str]
    # Structured result
    result_component_type: str
    table_columns: list[Any] | None = None
    table_rows: list[Any] | None = None
    chart_type: str | None = None
    chart_data: list[Any] | None = None
    source_tables: list[str]
    data_confidence: dict
    suggested_next_actions: list[str]
    llm_available: bool


class FeedbackPayload(BaseModel):
    score: int  # 1 = thumbs up, -1 = thumbs down


@router.post("/query", response_model=ChatResponse)
def chat_query(
    payload: ChatQuery,
    db: Session = Depends(get_db),
) -> ChatResponse:
    """
    Classify intent → call allow-listed backend tools → generate sourced answer.

    recommendation_request fires BEFORE any tool call and returns the
    CHAT_RECOMMENDATION_REFRAME_V1 template unconditionally.

    Every tool call is logged to tool_call_log with the thread_id.
    After the assistant message is saved, tool_call_log.message_id is backfilled.
    """

    # ── 1. Thread ─────────────────────────────────────────────────────────
    thread: ChatThread | None = None
    if payload.thread_id:
        try:
            thread = db.get(ChatThread, uuid.UUID(payload.thread_id))
        except (ValueError, Exception):
            thread = None

    if thread is None:
        thread = ChatThread(title=payload.message[:80])
        db.add(thread)
        db.flush()

    thread_id_str = str(thread.id)

    # ── 2. User message ───────────────────────────────────────────────────
    user_msg = ChatMessage(
        thread_id=thread.id,
        role="user",
        content=payload.message,
    )
    db.add(user_msg)
    db.flush()

    # ── 3. Classify intent ────────────────────────────────────────────────
    plan = classify_intent(payload.message)
    intent: str = plan["intent"]
    tool_names: list[str] = plan.get("tools", [])
    params: dict = plan.get("params", {})

    # Merge context.selected_entities into compare params
    if intent == "compare" and payload.context:
        ctx_entities = payload.context.get("selected_entities", [])
        if ctx_entities and not params.get("schemecodes"):
            # Expect list of ints or strings
            try:
                params["schemecodes"] = [int(e) for e in ctx_entities]
            except (TypeError, ValueError):
                pass

    # If LLM extracted a schemecode from message but context has override
    if payload.context and not params.get("schemecode"):
        ctx_fund = payload.context.get("primary_schemecode")
        if ctx_fund:
            params["schemecode"] = int(ctx_fund)

    # ── 4. Execute tools (skipped for recommendation_request) ─────────────
    tool_results: list[dict] = []
    tool_log: list[dict] = []

    if intent != "recommendation_request":
        for tool_name in tool_names:
            result = call_tool(tool_name, params, db, thread_id=thread_id_str)
            tool_results.append(result)
            tool_log.append({
                "tool": tool_name,
                "params": params,
                "ok": "error" not in result,
            })

    # ── 5. Generate structured response ───────────────────────────────────
    structured = generate_response(payload.message, intent, tool_results)

    answer: str = structured.get("answer", "")
    result_component_type: str = structured.get("result_component_type", "text")
    table_columns = structured.get("table_columns")
    table_rows = structured.get("table_rows")
    chart_type = structured.get("chart_type")
    chart_data = structured.get("chart_data")
    source_tables: list[str] = structured.get("source_tables", [])
    data_confidence: dict = structured.get("data_confidence", {"level": "low", "coverage": 0.0, "recency": "N/A"})
    suggested_next_actions: list[str] = structured.get("suggested_next_actions", [])
    llm_available: bool = structured.get("llm_available", False)

    # ── 6. Save assistant message ──────────────────────────────────────────
    conf_label = plan.get("classifier", "keyword")
    sources = source_tables or ["selfmade_ranking_snapshot"]

    assistant_msg = ChatMessage(
        thread_id=thread.id,
        role="assistant",
        content=answer,
        sources=sources,
        intent=intent,
        confidence=data_confidence.get("level", "medium"),
        result_component_type=result_component_type,
        table_columns=table_columns,
        table_rows=table_rows,
        chart_type=chart_type,
        chart_data=chart_data,
        source_tables=source_tables,
        data_confidence=data_confidence,
        suggested_next_actions=suggested_next_actions,
    )
    db.add(assistant_msg)
    db.flush()

    # ── 7. Backfill tool_call_log.message_id ──────────────────────────────
    if tool_log:
        db.execute(
            text(
                "UPDATE tool_call_log SET message_id = :mid "
                "WHERE thread_id = :tid AND message_id IS NULL"
            ),
            {"mid": assistant_msg.id, "tid": thread.id},
        )

    thread.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(assistant_msg)

    return ChatResponse(
        thread_id=thread_id_str,
        message_id=assistant_msg.id,
        answer=answer,
        intent=intent,
        tool_calls=tool_log,
        sources=sources,
        result_component_type=result_component_type,
        table_columns=table_columns,
        table_rows=table_rows,
        chart_type=chart_type,
        chart_data=chart_data,
        source_tables=source_tables,
        data_confidence=data_confidence,
        suggested_next_actions=suggested_next_actions,
        llm_available=llm_available,
    )


@router.get("/threads")
def list_recent_threads(
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
) -> dict:
    """Return the most recently updated chat threads."""
    threads = db.execute(
        select(ChatThread).order_by(desc(ChatThread.updated_at)).limit(limit)
    ).scalars().all()
    return {
        "threads": [
            {
                "thread_id": str(t.id),
                "title": t.title or "Untitled chat",
                "updated_at": t.updated_at.isoformat(),
            }
            for t in threads
        ]
    }


@router.get("/threads/{thread_id}/messages")
def get_thread_messages(
    thread_id: str,
    db: Session = Depends(get_db),
) -> dict:
    """Return all messages in a thread."""
    try:
        tid = uuid.UUID(thread_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid thread_id")

    thread = db.get(ChatThread, tid)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")

    msgs = db.execute(
        select(ChatMessage)
        .where(ChatMessage.thread_id == tid)
        .order_by(ChatMessage.created_at)
    ).scalars().all()

    return {
        "thread_id": thread_id,
        "title": thread.title,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "intent": m.intent,
                "result_component_type": m.result_component_type,
                "table_columns": m.table_columns,
                "table_rows": m.table_rows,
                "chart_type": m.chart_type,
                "chart_data": m.chart_data,
                "source_tables": m.source_tables,
                "data_confidence": m.data_confidence,
                "suggested_next_actions": m.suggested_next_actions,
                "feedback_score": m.feedback_score,
                "created_at": m.created_at.isoformat(),
            }
            for m in msgs
        ],
    }


@router.patch("/messages/{message_id}/feedback")
def record_feedback(
    message_id: int,
    payload: FeedbackPayload,
    db: Session = Depends(get_db),
) -> dict:
    """Record thumbs-up (1) or thumbs-down (-1) for an assistant message."""
    msg = db.get(ChatMessage, message_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="Message not found")
    if msg.role != "assistant":
        raise HTTPException(status_code=400, detail="Feedback only applies to assistant messages")
    if payload.score not in (-1, 0, 1):
        raise HTTPException(status_code=422, detail="score must be -1, 0, or 1")
    msg.feedback_score = payload.score
    db.commit()
    return {"message_id": message_id, "feedback_score": payload.score}
