"""Comparison session endpoints — history, saved comparisons, and fund data."""

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.comparison import ComparisonSession
from app.services.compare_service import build_fund_comparison

router = APIRouter(prefix="/compare", tags=["compare"])


class CreateSessionRequest(BaseModel):
    fund_ids: list[str]
    label: str | None = None
    is_saved: bool = False


class SaveSessionRequest(BaseModel):
    label: str | None = None


def _session_out(s: ComparisonSession) -> dict:
    return {
        "id": str(s.id),
        "fund_ids": s.fund_ids,
        "label": s.label,
        "is_saved": s.is_saved,
        "created_at": s.created_at.isoformat(),
    }


@router.post("/sessions")
def create_session(
    body: CreateSessionRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Auto-save a comparison (history) or explicitly save one."""
    session = ComparisonSession(
        id=uuid.uuid4(),
        fund_ids=body.fund_ids,
        label=body.label,
        is_saved=body.is_saved,
        created_at=datetime.utcnow(),
    )
    db.add(session)
    # Prune unsaved history older than the 10 most recent
    if not body.is_saved:
        unsaved = db.execute(
            select(ComparisonSession)
            .where(ComparisonSession.is_saved == False)  # noqa: E712
            .order_by(desc(ComparisonSession.created_at))
        ).scalars().all()
        for old in unsaved[10:]:
            db.delete(old)
    db.commit()
    db.refresh(session)
    return _session_out(session)


@router.get("/sessions")
def list_sessions(
    saved_only: bool = Query(default=False),
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
) -> dict:
    """Return recent history (saved_only=false) or saved comparisons (saved_only=true)."""
    q = select(ComparisonSession)
    if saved_only:
        q = q.where(ComparisonSession.is_saved == True)  # noqa: E712
    q = q.order_by(desc(ComparisonSession.created_at)).limit(limit)
    sessions = db.execute(q).scalars().all()
    return {"sessions": [_session_out(s) for s in sessions]}


@router.patch("/sessions/{session_id}/save")
def save_session(
    session_id: str,
    body: SaveSessionRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Mark an existing session as saved (bookmark it)."""
    session = db.get(ComparisonSession, uuid.UUID(session_id))
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    session.is_saved = True
    if body.label:
        session.label = body.label
    db.commit()
    db.refresh(session)
    return _session_out(session)


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(
    session_id: str,
    db: Session = Depends(get_db),
) -> None:
    """Delete a comparison session."""
    session = db.get(ComparisonSession, uuid.UUID(session_id))
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    db.delete(session)
    db.commit()


# ── POST /compare/funds — real data for selected funds ────────────────────────

class CompareFundsRequest(BaseModel):
    schemecodes: list[int]
    evaluation_date: date | None = None


@router.post("/funds")
def compare_funds(
    body: CompareFundsRequest,
    db: Session = Depends(get_db),
) -> dict:
    """
    Return side-by-side metrics for 2–4 selected funds.
    Thin HTTP wrapper — build_fund_comparison() (app/services/compare_service.py)
    is the one canonical implementation, shared with the compare_funds chat tool
    (app/ai/tools.py) so both surfaces get the same honest-degradation behavior
    for a fund outside the governed ranked universe.
    """
    if not body.schemecodes or len(body.schemecodes) < 2:
        raise HTTPException(status_code=400, detail="Provide at least 2 schemecodes")
    if len(body.schemecodes) > 4:
        raise HTTPException(status_code=400, detail="Maximum 4 funds per comparison")

    try:
        return build_fund_comparison(db, body.schemecodes, body.evaluation_date)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
