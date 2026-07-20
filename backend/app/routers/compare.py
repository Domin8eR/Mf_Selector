"""Comparison session endpoints — history, saved comparisons, and fund data."""

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.insights.calculator import (
    get_active_share_for_fund,
    get_aum_for_fund,
    get_common_holdings_table,
    get_expense_ratio_for_fund,
    get_overlap_metrics,
    get_portfolio_stability_for_fund,
    get_sector_overlap_table,
)
from app.models.comparison import ComparisonSession

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


def _percentile_rank_in_list(values: list[float | None], idx: int, lower_better: bool = False) -> float | None:
    """
    Rank the value at `idx` among the non-None values in `values`.
    Returns 0–100 scaled rank. lower_better=True inverts the direction.
    """
    val = values[idx]
    if val is None:
        return None
    non_none = [v for v in values if v is not None]
    if not non_none:
        return None
    rank = sum(1 for v in non_none if v <= val)
    pct = rank / len(non_none) * 100.0
    return round(100.0 - pct if lower_better else pct, 2)


@router.post("/funds")
def compare_funds(
    body: CompareFundsRequest,
    db: Session = Depends(get_db),
) -> dict:
    """
    Return side-by-side metrics for 2–4 selected funds.
    All data is pre-computed — no vendor API calls at request time.
    Includes active_share, portfolio_stability, expense_ratio_pct,
    holdings_overlap, sector_table, radar_data (2-fund), rank_history, advantages.
    """
    if not body.schemecodes or len(body.schemecodes) < 2:
        raise HTTPException(status_code=400, detail="Provide at least 2 schemecodes")
    if len(body.schemecodes) > 4:
        raise HTTPException(status_code=400, detail="Maximum 4 funds per comparison")

    eval_date = body.evaluation_date or date.today()

    fund_rows = db.execute(text("""
        SELECT
            s.schemecode,
            s.fund_name,
            s.rank_in_category,
            s.composite_score_v2,
            s.category,
            s.snapshot_date,
            s.rank_delta_6m,
            sm.information_ratio_3yr,
            sm.sharpe_ratio_3yr,
            sm.tracking_error_3yr,
            sm.ir_slope_6m_proxy,
            sr.active_3yr_ret,
            sr.fund_1yr_ret,
            sr.fund_3yr_ret,
            sr.fund_5yr_ret,
            COALESCE(a.s_name, 'Unknown AMC') AS amc_name,
            sm.outperformed_3yr
        FROM selfmade_ranking_snapshot s
        JOIN selfmade_scheme_metrics sm ON sm.schemecode = s.schemecode
        LEFT JOIN selfmade_scheme_returns sr ON sr.schemecode = s.schemecode
        LEFT JOIN altstreet_scheme_master asm ON asm.scheme_id::integer = s.schemecode
        LEFT JOIN amc_mst_new a ON a.amc_code = asm.amc::integer
        WHERE s.schemecode = ANY(:codes)
          AND s.snapshot_date = (
              SELECT MAX(snapshot_date) FROM selfmade_ranking_snapshot
              WHERE schemecode = s.schemecode AND snapshot_date <= :ed
          )
        ORDER BY s.composite_score_v2 DESC NULLS LAST
    """), {"codes": body.schemecodes, "ed": str(eval_date)}).fetchall()

    if not fund_rows:
        raise HTTPException(status_code=404, detail="No data found for the requested funds")

    # ── Build per-fund records ────────────────────────────────────────────────
    funds: list[dict] = []
    for r in fund_rows:
        (sc, name, rank, score, cat, snap_dt, delta6m,
         ir3, sharpe3, te3, slope, active_ret,
         ret1y, ret3y, ret5y, amc, outperf3yr) = r

        total_in_cat = db.execute(text("""
            SELECT COUNT(*) FROM selfmade_ranking_snapshot
            WHERE snapshot_date = :dt AND category = :cat
        """), {"dt": snap_dt, "cat": cat}).scalar() or 1

        pct = 1.0 - (rank - 1) / max(total_in_cat, 1)
        if pct >= 0.85:
            status = "Strong"
        elif pct >= 0.50:
            status = "Good"
        elif pct >= 0.15:
            status = "Neutral"
        else:
            status = "Weak"

        # ── Compute new per-fund metrics ──────────────────────────────────────
        active_share_result = get_active_share_for_fund(db, sc)
        stability_result = get_portfolio_stability_for_fund(db, sc)
        expense_result = get_expense_ratio_for_fund(db, sc)
        aum_result = get_aum_for_fund(db, sc)

        # outperformance_ratio: use outperformed_3yr bool as 0.0/1.0 proxy
        if outperf3yr is not None:
            outperf_ratio: float | None = 1.0 if bool(outperf3yr) else 0.0
        else:
            outperf_ratio = None

        funds.append({
            "schemecode": sc,
            "fund_name": name,
            "amc_name": amc,
            "category": cat,
            "rank": rank,
            "total_in_category": total_in_cat,
            "composite_score": round(float(score or 0), 2),
            "status_label": status,
            "rank_delta_6m": int(delta6m) if delta6m is not None else None,
            "as_of_date": str(snap_dt),
            "aum_cr": aum_result["value"],
            "active_share": active_share_result,
            "portfolio_stability": stability_result,
            "expense_ratio_pct": expense_result,
            "outperformance_ratio": {
                "value": outperf_ratio,
                "status": "ok" if outperf_ratio is not None else "insufficient_data",
            },
            "max_drawdown_pct": {
                "value": None,
                "status": "insufficient_data",
                "confidence": "insufficient_data",
            },
            "downside_capture_ratio": {
                "value": None,
                "status": "insufficient_data",
                "confidence": "insufficient_data",
            },
            "metrics": {
                "ir_3yr":             round(float(ir3), 4)        if ir3        is not None else None,
                "sharpe_3yr":         round(float(sharpe3), 4)    if sharpe3    is not None else None,
                "tracking_error_3yr": round(float(te3), 4)        if te3        is not None else None,
                "ir_slope_6m_proxy":  round(float(slope), 6)      if slope      is not None else None,
                "active_ret_3yr":     round(float(active_ret), 4) if active_ret is not None else None,
                "ret_1yr":            round(float(ret1y), 4)      if ret1y      is not None else None,
                "ret_3yr":            round(float(ret3y), 4)      if ret3y      is not None else None,
                "ret_5yr":            round(float(ret5y), 4)      if ret5y      is not None else None,
            },
        })

    schemecodes = [f["schemecode"] for f in funds]
    is_two_fund = len(funds) == 2
    layout = "A" if is_two_fund else "B"

    # ── Holdings overlap ──────────────────────────────────────────────────────
    overlap = get_overlap_metrics(db, schemecodes)
    common_holdings: list[dict] = []
    if is_two_fund:
        common_holdings = get_common_holdings_table(db, schemecodes[0], schemecodes[1])

    sector_table = get_sector_overlap_table(db, schemecodes)

    holdings_overlap = {
        "weighted_overlap": overlap["weighted_overlap"],
        "jaccard": overlap["jaccard"],
        "sector_overlap": overlap["sector_overlap"],
        "common_count": overlap["common_count"],
        "pairs": overlap["pairs"],
        "common_holdings": common_holdings,
        "sector_table": sector_table,
    }

    # ── Radar data (2-fund only) ──────────────────────────────────────────────
    radar_data: dict | None = None
    if is_two_fund:
        ir_vals    = [f["metrics"]["ir_3yr"] for f in funds]
        as_vals    = [f["active_share"].get("value") for f in funds]
        er_vals    = [f["expense_ratio_pct"].get("value") for f in funds]
        stab_vals  = [f["portfolio_stability"].get("value") for f in funds]

        radar_data = {}
        for idx, f in enumerate(funds):
            sc = f["schemecode"]
            radar_data[sc] = {
                "ir_3yr_normalized":          _percentile_rank_in_list(ir_vals, idx, lower_better=False),
                "downside_protection":        None,  # no daily NAV yet
                "active_share_normalized":    _percentile_rank_in_list(as_vals, idx, lower_better=False),
                "expense_efficiency":         _percentile_rank_in_list(er_vals, idx, lower_better=True),
                "portfolio_stability_normalized": _percentile_rank_in_list(stab_vals, idx, lower_better=False),
            }

    # ── Advantages (which fund wins each metric) ──────────────────────────────
    def _best_sc(metric_fn, lower_better: bool = False) -> int | None:
        """Return schemecode of fund with best value for the metric. None if tied/missing."""
        candidates = [(f["schemecode"], metric_fn(f)) for f in funds]
        candidates = [(sc, v) for sc, v in candidates if v is not None]
        if not candidates:
            return None
        return (min if lower_better else max)(candidates, key=lambda x: x[1])[0]

    advantages = {
        "ir_3yr":               _best_sc(lambda f: f["metrics"]["ir_3yr"]),
        "ir_slope_6m_proxy":    _best_sc(lambda f: f["metrics"]["ir_slope_6m_proxy"]),
        "active_ret_3yr":       _best_sc(lambda f: f["metrics"]["active_ret_3yr"]),
        "ret_3yr":              _best_sc(lambda f: f["metrics"]["ret_3yr"]),
        "ret_1yr":              _best_sc(lambda f: f["metrics"]["ret_1yr"]),
        "active_share":         _best_sc(lambda f: f["active_share"].get("value")),
        "portfolio_stability":  _best_sc(lambda f: f["portfolio_stability"].get("value")),
        "outperformance_ratio": _best_sc(lambda f: f["outperformance_ratio"].get("value")),
        "expense_ratio_pct":    _best_sc(lambda f: f["expense_ratio_pct"].get("value"), lower_better=True),
        "max_drawdown_pct":     _best_sc(lambda f: f["max_drawdown_pct"].get("value"), lower_better=True),
        "downside_capture_ratio": _best_sc(lambda f: f["downside_capture_ratio"].get("value"), lower_better=True),
        "composite_score":      _best_sc(lambda f: f["composite_score"]),
    }

    # ── Rank history (2-fund only) ────────────────────────────────────────────
    rank_history: dict | None = None
    if is_two_fund:
        hist_rows = db.execute(text("""
            SELECT schemecode, snapshot_date, rank_in_category
            FROM selfmade_ranking_snapshot
            WHERE schemecode = ANY(:codes)
            ORDER BY schemecode, snapshot_date
        """), {"codes": schemecodes}).fetchall()

        rank_history = {sc: [] for sc in schemecodes}
        for sc_h, snap_dt, rank_h in hist_rows:
            if sc_h in rank_history:
                rank_history[sc_h].append({"date": str(snap_dt), "rank": rank_h})

    return {
        "funds": funds,
        "layout": layout,
        "evaluation_date": str(eval_date),
        "holdings_overlap": holdings_overlap,
        "radar_data": radar_data,
        "advantages": advantages,
        "rank_history": rank_history,
        "data_version": settings.data_version,
        "rule_version": "v1.0",
        "calculation_version": "2.0",
    }
