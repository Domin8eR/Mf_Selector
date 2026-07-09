"""Audit trail endpoints — immutable governance log."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import get_db

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/rule-history")
def rule_audit_history(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    """
    Chronological audit_event feed for the Rule Approval page's Audit Log strip.
    Returns actor, action, rule_version_id, comment, timestamp — newest first.
    """
    rows = db.execute(text("""
        SELECT
            ae.id,
            ae.action,
            ae.actor,
            ae.rule_version_id,
            ae.comment,
            ae.created_at,
            rv.version_label
        FROM selfmade_audit_event ae
        LEFT JOIN selfmade_rule_version rv ON rv.id = ae.rule_version_id
        ORDER BY ae.created_at DESC
        LIMIT :lim
    """), {"lim": limit}).fetchall()

    return {
        "events": [
            {
                "id":               r[0],
                "action":           r[1],
                "actor":            r[2],
                "rule_version_id":  r[3],
                "comment":          r[4],
                "created_at":       r[5].isoformat() if r[5] else None,
                "version_label":    r[6],
            }
            for r in rows
        ],
        "total": len(rows),
    }
