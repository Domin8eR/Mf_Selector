"""Workspaces — AI Workspace persistence and NL query interpretation.

Endpoints:
  GET  /workspaces/recent              — 5 most-recently-updated saved workspaces
  GET  /workspaces/{id}                — one workspace + live-recomputed scatter data
  POST /workspaces                     — create a real workspace row (replaces seed data)
  POST /workspace/interpret-query      — NL query → lens spec (reuses Supervisor)

The recommendation-reframe guard from Research Chat runs inside interpret-query —
this page can receive disguised suitability questions just as easily as chat can.
"""

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.insights.renderer import render_insight_template

router = APIRouter(prefix="/workspaces", tags=["workspaces"])
_interpret_router = APIRouter(prefix="/workspace", tags=["workspaces"])


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class CreateWorkspaceRequest(BaseModel):
    name: str
    category: str = "Equity — Large Cap"
    x_metric: str = "information_ratio_3yr"
    y_metric: str = "ir_slope_6m_proxy"
    query_text: str | None = None
    filter_summary: str | None = None


class InterpretQueryRequest(BaseModel):
    message: str
    category: str | None = None


# ── Helper: workspace row → dict ──────────────────────────────────────────────

def _ws_out(r: tuple) -> dict:
    return {
        "id":             int(r[0]),
        "name":           r[1],
        "description":    r[2],
        "category":       r[3],
        "x_metric":       r[4],
        "y_metric":       r[5],
        "query_text":     r[6],
        "filter_summary": r[7],
        "owner":          r[8],
        "updated_at":     r[9].isoformat() if r[9] else None,
        "created_at":     r[10].isoformat() if r[10] else None,
    }


_WS_COLS = """
    id, name, description, category, x_metric, y_metric,
    query_text, filter_summary, owner, updated_at, created_at
"""


# ── Insight generation for a lens workspace ───────────────────────────────────

def _generate_lens_insights(
    category: str,
    x_metric: str,
    y_metric: str,
    x_label: str,
    y_label: str,
    x_threshold: float,
    y_threshold: float,
    quadrant_filter: str | None,
    points: list[dict],
) -> list[dict]:
    """
    Deterministic insight cards for the AI Workspace lens panel.
    Three templates — always: LENS_QUADRANT_EXPLAINER_V1,
    then either LENS_CANDIDATES_FOUND_V1 or LENS_CANDIDATES_NONE_V1.
    """
    from app.routers.metrics import _lens_direction_phrase, _lens_y_axis_meaning, _lens_threshold_phrase

    cards = []

    explainer = render_insight_template("LENS_QUADRANT_EXPLAINER_V1", {
        "category":           category,
        "fund_count":         len(points),
        "x_label":            x_label,
        "y_label":            y_label,
        "x_direction_phrase": _lens_direction_phrase(x_metric, x_label),
        "y_axis_meaning":     _lens_y_axis_meaning(y_metric, y_label),
        "x_threshold_phrase": _lens_threshold_phrase(x_label, x_threshold),
        "y_threshold_phrase": _lens_threshold_phrase(y_label, y_threshold),
    })
    if explainer:
        cards.append(explainer.model_dump())

    target_q = quadrant_filter or "improving-strong"
    q_label = target_q.replace("-", " ").title()
    filter_text = (
        f"{x_label} {'≥' if 'strong' in target_q else '<'} median "
        f"AND {y_label} {'≥' if 'improving' in target_q else '<'} {y_threshold}"
    )

    filtered = [p for p in points if p["quadrant"] == target_q]
    count = len(filtered)

    if count > 0:
        top5 = sorted(filtered, key=lambda p: p["x_value"], reverse=True)[:5]
        top_text = "; ".join(
            f"{p['fund_name']} ({p['x_value']:.3f})" for p in top5
        )
        card = render_insight_template("LENS_CANDIDATES_FOUND_V1", {
            "count":         count,
            "category":      category,
            "quadrant_label": q_label,
            "filter_summary": filter_text,
            "x_label":       x_label,
            "top_candidates": top_text,
        })
    else:
        card = render_insight_template("LENS_CANDIDATES_NONE_V1", {
            "quadrant_label": q_label,
            "filter_summary": filter_text,
            "category":      category,
        })

    if card:
        cards.append(card.model_dump())

    return cards


# ── GET /workspaces/recent ────────────────────────────────────────────────────

@router.get("/recent")
def recent_workspaces(
    limit: int = Query(default=5, ge=1, le=20),
    db: Session = Depends(get_db),
) -> dict:
    """Return the most recently updated saved workspaces."""
    rows = db.execute(text(f"""
        SELECT {_WS_COLS}
        FROM selfmade_workspace
        ORDER BY updated_at DESC
        LIMIT :lim
    """), {"lim": limit}).fetchall()

    return {
        "workspaces": [_ws_out(r) for r in rows],
        "as_of_date": str(date.today()),
    }


# ── POST /workspaces ──────────────────────────────────────────────────────────

@router.post("", status_code=201)
def create_workspace(
    body: CreateWorkspaceRequest,
    db: Session = Depends(get_db),
) -> dict:
    """
    Persist a new workspace row.

    Sets description to filter_summary for backwards-compat with Home's
    Recent Workspaces card (which reads the description column).
    """
    now = datetime.utcnow()
    row = db.execute(text("""
        INSERT INTO selfmade_workspace
          (name, description, category, x_metric, y_metric, query_text, filter_summary,
           updated_at, created_at)
        VALUES
          (:name, :desc, :cat, :xm, :ym, :qt, :fs, :now, :now)
        RETURNING id, name, description, category, x_metric, y_metric,
                  query_text, filter_summary, owner, updated_at, created_at
    """), {
        "name": body.name[:300],
        "desc": (body.filter_summary or "")[:500],
        "cat":  body.category,
        "xm":   body.x_metric,
        "ym":   body.y_metric,
        "qt":   body.query_text,
        "fs":   body.filter_summary,
        "now":  now,
    }).fetchone()
    db.commit()
    return _ws_out(row)


# ── GET /workspaces/{id} ──────────────────────────────────────────────────────

@router.get("/{workspace_id}")
def get_workspace(
    workspace_id: int,
    db: Session = Depends(get_db),
) -> dict:
    """
    Load a saved workspace and recompute scatter data live from its stored filter spec.

    Scatter data is NEVER cached — always fresh from current selfmade_* tables.
    """
    ws_row = db.execute(text(f"""
        SELECT {_WS_COLS} FROM selfmade_workspace WHERE id = :id
    """), {"id": workspace_id}).fetchone()

    if not ws_row:
        raise HTTPException(status_code=404, detail=f"Workspace {workspace_id} not found")

    ws = _ws_out(ws_row)

    # Live-recompute scatter data from saved filter spec
    x_metric = ws["x_metric"] or "information_ratio_3yr"
    y_metric  = ws["y_metric"] or "ir_slope_6m_proxy"
    category  = ws["category"] or "Equity — Large Cap"

    from app.routers.metrics import (
        _LENS_LABELS, _LENS_HIGHER_BETTER,
        _LENS_Y_THRESHOLD, _assign_quadrant, _compute_quadrant_counts, _trend_note,
    )

    rows = db.execute(text("""
        SELECT
            s.schemecode, s.fund_name,
            s.information_ratio_3yr, s.composite_score_v2,
            s.sharpe_score, s.rank_delta_6m, s.rank_in_category,
            sm.ir_slope_6m_proxy,
            sr.active_3yr_ret, sr.fund_3yr_ret, sr.fund_5yr_ret, sr.fund_1yr_ret
        FROM selfmade_ranking_snapshot s
        LEFT JOIN selfmade_scheme_metrics sm ON sm.schemecode = s.schemecode
        LEFT JOIN selfmade_scheme_returns sr ON sr.schemecode = s.schemecode
        WHERE s.category = :cat
          AND s.snapshot_date = (
              SELECT MAX(snapshot_date) FROM selfmade_ranking_snapshot WHERE category = :cat
          )
        ORDER BY s.rank_in_category
    """), {"cat": category}).fetchall()

    col_map = {
        "information_ratio_3yr": 2, "composite_score_v2": 3, "sharpe_score": 4,
        "rank_delta_6m": 5, "ir_slope_6m_proxy": 7,
        "active_3yr_ret": 8, "fund_3yr_ret": 9, "fund_5yr_ret": 10, "fund_1yr_ret": 11,
    }
    x_idx = col_map.get(x_metric, 2)
    y_idx = col_map.get(y_metric, 7)

    x_raw = [float(r[x_idx]) for r in rows if r[x_idx] is not None]
    y_raw = [float(r[y_idx]) for r in rows if r[y_idx] is not None]

    x_threshold = 0.0
    if x_raw:
        xs = sorted(x_raw)
        n = len(xs)
        x_threshold = (xs[n // 2 - 1] + xs[n // 2]) / 2 if n % 2 == 0 else xs[n // 2]

    y_threshold = _LENS_Y_THRESHOLD.get(y_metric, None)
    if y_threshold is None and y_raw:
        ys = sorted(y_raw)
        yn = len(ys)
        y_threshold = (ys[yn // 2 - 1] + ys[yn // 2]) / 2 if yn % 2 == 0 else ys[yn // 2]
    if y_threshold is None:
        y_threshold = 0.0

    y_higher_better = _LENS_HIGHER_BETTER.get(y_metric, True)
    points = []
    for r in rows:
        xv = float(r[x_idx]) if r[x_idx] is not None else None
        yv = float(r[y_idx]) if r[y_idx] is not None else None
        if xv is None or yv is None:
            continue
        q = _assign_quadrant(xv, yv, x_threshold, y_threshold, y_higher_better)
        points.append({
            "schemecode":       int(r[0]),
            "fund_name":        r[1],
            "x_value":          round(xv, 6),
            "y_value":          round(yv, 6),
            "quadrant":         q,
            "ir_3yr":           round(float(r[2]), 4) if r[2] is not None else None,
            "rank_in_category": int(r[6]) if r[6] is not None else None,
            "rank_delta_6m":    int(r[5]) if r[5] is not None else None,
            "note":             _trend_note(
                                    float(r[7]) if r[7] is not None else None,
                                    int(r[5]) if r[5] is not None else None,
                                ),
        })

    x_label = _LENS_LABELS.get(x_metric, x_metric)
    y_label = _LENS_LABELS.get(y_metric, y_metric)

    insights = _generate_lens_insights(
        category=category,
        x_metric=x_metric,
        y_metric=y_metric,
        x_label=x_label,
        y_label=y_label,
        x_threshold=x_threshold,
        y_threshold=y_threshold,
        quadrant_filter=None,
        points=points,
    )

    return {
        **ws,
        "scatter": {
            "x_metric":     x_metric,
            "y_metric":     y_metric,
            "x_label":      x_label,
            "y_label":      y_label,
            "x_threshold":  round(x_threshold, 6),
            "y_threshold":  round(y_threshold, 6),
            "total_funds":  len(points),
            "quadrant_counts": _compute_quadrant_counts(points),
            "points":       points,
        },
        "insights": insights,
    }


# ── POST /workspace/interpret-query ──────────────────────────────────────────

@_interpret_router.post("/interpret-query")
def interpret_query(
    body: InterpretQueryRequest,
    db: Session = Depends(get_db),
) -> dict:
    """
    Parse a natural-language workspace query into a structured lens spec.

    The recommendation-reframe guard from Research Chat runs first —
    suitability questions are refused here exactly as in chat (Section 8.3).

    Returns a lens spec: {x_metric, y_metric, x_label, y_label, category,
    quadrant_filter, filter_summary_text, refusal_reason (null unless guard fires)}.
    """
    from app.ai.supervisor import classify_lens_query

    spec = classify_lens_query(body.message)

    # If a category override is provided by the caller, apply it
    if body.category and not spec.get("refusal_reason"):
        spec["category"] = body.category

    return spec
