"""
Rankings endpoints — reads from selfmade_ranking_snapshot (rule-engine-scored).

Scoring: weighted percentile normalization using selfmade_rule_component weights.
Components: 3Y IR (0.40), Sharpe 3Y proxy (0.25), Active Ret 3Y (0.20), TE 3Y lower_better (0.15).
All ranks, scores, and contributions come from pre-computed DB tables.

Language rule: NEVER use "recommend", "buy", "sell", "best fund", "top pick".
Use: "structural improvement", "research candidate", "ranked funds".
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db

router = APIRouter(prefix="/rankings", tags=["rankings"])

# ── Status label cutoffs (configurable constants — not hardcoded ifs) ─────────
_STATUS_CUTOFFS = [
    (0.85, "Strong"),
    (0.50, "Good"),
    (0.15, "Neutral"),
    (0.00, "Weak"),
]

LATEST_RULE_VERSION = "v1.0"
SORT_BASIS = "RULE_ENGINE_V1"


def _status_label(rank: int, total: int) -> str:
    pct = 1.0 - (rank - 1) / max(total, 1)
    for threshold, label in _STATUS_CUTOFFS:
        if pct >= threshold:
            return label
    return "Weak"


# ── /rankings/recent-runs ─────────────────────────────────────────────────────

@router.get("/recent-runs")
def recent_ranking_runs_v1(
    limit: int = Query(default=5, ge=1, le=20),
    db: Session = Depends(get_db),
) -> dict:
    """Return recent ranking runs from selfmade_ranking_snapshot."""
    rows = db.execute(text("""
        SELECT
            snapshot_date,
            category,
            COUNT(*) AS fund_count,
            AVG(composite_score_v2) AS avg_score,
            sort_basis
        FROM selfmade_ranking_snapshot
        GROUP BY snapshot_date, category, sort_basis
        ORDER BY snapshot_date DESC, category
        LIMIT :lim
    """), {"lim": limit}).fetchall()

    return {
        "runs": [
            {
                "run_date": str(r[0]),
                "category": r[1],
                "fund_count": r[2],
                "sort_basis": r[4] or SORT_BASIS,
                "avg_score": round(float(r[3]), 2) if r[3] else None,
                "rule_version": LATEST_RULE_VERSION,
                "calculation_version": "2.0",
            }
            for r in rows
        ],
        "as_of_date": str(date.today()),
        "data_version": settings.data_version,
    }


# ── /rankings/category ────────────────────────────────────────────────────────

@router.get("/category")
def get_category_rankings(
    category: str = Query(default="Equity — Large Cap"),
    evaluation_date: str | None = Query(
        default=None,
        description="YYYY-MM-DD. Omit for latest snapshot.",
    ),
    rule_set_id: str | None = Query(default=None),
    search: str | None = Query(default=None, description="Filter by fund name substring"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    """
    Return ranked funds for a category from the rule-engine snapshot.
    Scores come from selfmade_ranking_snapshot + contributions from
    selfmade_ranking_contribution.
    """
    # Resolve evaluation_date to the latest available snapshot
    if evaluation_date:
        snap_date_row = db.execute(text("""
            SELECT MAX(snapshot_date) FROM selfmade_ranking_snapshot
            WHERE category = :cat AND snapshot_date <= :ed::date
        """), {"cat": category, "ed": evaluation_date}).fetchone()
    else:
        snap_date_row = db.execute(text("""
            SELECT MAX(snapshot_date) FROM selfmade_ranking_snapshot
            WHERE category = :cat
        """), {"cat": category}).fetchone()

    if not snap_date_row or not snap_date_row[0]:
        return {
            "data_version": settings.data_version,
            "rule_version": LATEST_RULE_VERSION,
            "calculation_version": "2.0",
            "as_of_date": str(date.today()),
            "evaluation_date": evaluation_date or str(date.today()),
            "category": category,
            "sort_basis": SORT_BASIS,
            "total": 0,
            "page": page,
            "page_size": page_size,
            "results": [],
        }

    snap_date = snap_date_row[0]

    # Fetch ranked rows with component scores
    search_filter = f"%{search}%" if search else None
    rows = db.execute(text("""
        SELECT
            s.schemecode,
            s.fund_name,
            s.rank_in_category,
            s.composite_score_v2,
            s.information_ratio_3yr,
            s.rank_delta_6m,
            sm.sharpe_ratio_3yr,
            sm.tracking_error_3yr,
            sm.ir_slope_6m_proxy,
            sr.active_3yr_ret,
            sr.fund_1yr_ret,
            sr.fund_3yr_ret,
            COALESCE(a.s_name, 'Unknown AMC') AS amc_name,
            s.composite_score_v2 AS prev_score
        FROM selfmade_ranking_snapshot s
        JOIN selfmade_scheme_metrics sm ON sm.schemecode = s.schemecode
        LEFT JOIN selfmade_scheme_returns sr ON sr.schemecode = s.schemecode
        LEFT JOIN altstreet_scheme_master asm ON asm.scheme_id::integer = s.schemecode
        LEFT JOIN amc_mst_new a ON a.amc_code = asm.amc::integer
        WHERE s.snapshot_date = :snap_date
          AND s.category = :cat
          AND (:search IS NULL OR s.fund_name ILIKE :search)
        ORDER BY s.rank_in_category
    """), {
        "snap_date": snap_date,
        "cat": category,
        "search": search_filter,
    }).fetchall()

    total = len(rows)
    start = (page - 1) * page_size
    paged = rows[start: start + page_size]

    results = []
    for r in paged:
        sc, name, rank, score, ir3, delta6m, sharpe, te, slope, active_ret, ret1y, ret3y, amc, _ = r
        results.append({
            "schemecode": sc,
            "fund_name": name,
            "amc_name": amc,
            "rank": rank,
            "composite_score": round(float(score or 0), 2),
            "status_label": _status_label(rank, total),
            "rank_delta_6m": int(delta6m) if delta6m is not None else None,
            "ir_3yr": round(float(ir3), 4) if ir3 is not None else None,
            "sharpe_3yr": round(float(sharpe), 4) if sharpe is not None else None,
            "tracking_error_3yr": round(float(te), 4) if te is not None else None,
            "ir_slope_6m_proxy": round(float(slope), 6) if slope is not None else None,
            "active_ret_3yr": round(float(active_ret), 4) if active_ret is not None else None,
            "ret_1yr": round(float(ret1y), 4) if ret1y is not None else None,
            "ret_3yr": round(float(ret3y), 4) if ret3y is not None else None,
        })

    return {
        "data_version": settings.data_version,
        "rule_version": LATEST_RULE_VERSION,
        "calculation_version": "2.0",
        "as_of_date": str(snap_date),
        "evaluation_date": str(snap_date),
        "category": category,
        "sort_basis": SORT_BASIS,
        "total": total,
        "page": page,
        "page_size": page_size,
        "results": results,
    }


# ── /rankings/history — bump chart data ──────────────────────────────────────

@router.get("/history")
def get_ranking_history(
    category: str = Query(default="Equity — Large Cap"),
    top_n: int = Query(default=10, ge=3, le=30, description="Track top-N funds"),
    db: Session = Depends(get_db),
) -> dict:
    """
    Return rank history across 6 evaluation dates for the top-N funds.
    Used to render the bump chart in the Category Rankings page.
    """
    # Resolve top-N schemecodes from the latest snapshot
    latest_date = db.execute(text("""
        SELECT MAX(snapshot_date) FROM selfmade_ranking_snapshot
        WHERE category = :cat
    """), {"cat": category}).scalar()

    if not latest_date:
        return {"category": category, "dates": [], "series": []}

    top_codes = db.execute(text("""
        SELECT schemecode, fund_name, rank_in_category
        FROM selfmade_ranking_snapshot
        WHERE snapshot_date = :dt AND category = :cat
        ORDER BY rank_in_category
        LIMIT :n
    """), {"dt": latest_date, "cat": category, "n": top_n}).fetchall()

    if not top_codes:
        return {"category": category, "dates": [], "series": []}

    code_set = [r[0] for r in top_codes]
    name_map = {r[0]: r[1] for r in top_codes}

    # Get at most 6 evaluation dates (newest first, then reverse for chronological order)
    eval_dates_raw = db.execute(text("""
        SELECT DISTINCT snapshot_date
        FROM selfmade_ranking_snapshot
        WHERE category = :cat
        ORDER BY snapshot_date DESC
        LIMIT 6
    """), {"cat": category}).fetchall()
    eval_dates = list(reversed(eval_dates_raw))

    date_list = [str(r[0]) for r in eval_dates]

    # For each top fund, get its rank at each date
    history_rows = db.execute(text("""
        SELECT schemecode, snapshot_date, rank_in_category
        FROM selfmade_ranking_snapshot
        WHERE category = :cat
          AND schemecode = ANY(:codes)
        ORDER BY schemecode, snapshot_date
    """), {"cat": category, "codes": code_set}).fetchall()

    # Build per-fund series
    from collections import defaultdict
    fund_history: dict[int, dict[str, int]] = defaultdict(dict)
    for sc, dt, rank in history_rows:
        fund_history[sc][str(dt)] = rank

    series = []
    for sc in code_set:
        ranks_by_date = fund_history.get(sc, {})
        data_points = [
            {"date": d, "rank": ranks_by_date.get(d)}
            for d in date_list
        ]
        series.append({
            "schemecode": sc,
            "fund_name": name_map.get(sc, str(sc)),
            "latest_rank": ranks_by_date.get(date_list[-1]) if date_list else None,
            "data": data_points,
        })

    return {
        "category": category,
        "dates": date_list,
        "series": series,
        "as_of_date": str(latest_date),
        "data_version": settings.data_version,
    }


# ── /rankings/what-changed — 3 KPI tiles ─────────────────────────────────────

@router.get("/what-changed")
def get_what_changed(
    category: str = Query(default="Equity — Large Cap"),
    db: Session = Depends(get_db),
) -> dict:
    """
    Return 3 KPI tiles summarising what changed between the two most recent
    evaluation snapshots for a category.
    """
    dates = db.execute(text("""
        SELECT DISTINCT snapshot_date FROM selfmade_ranking_snapshot
        WHERE category = :cat
        ORDER BY snapshot_date DESC
        LIMIT 2
    """), {"cat": category}).fetchall()

    if len(dates) < 2:
        return {
            "category": category,
            "has_data": False,
            "tiles": [],
        }

    cur_date = dates[0][0]
    prev_date = dates[1][0]

    # Structural improvers: rank_delta ≤ -3 AND current_rank ≤ 30
    improver_count = db.execute(text("""
        SELECT COUNT(*)
        FROM selfmade_ranking_snapshot s_new
        JOIN selfmade_ranking_snapshot s_old
            ON s_old.schemecode = s_new.schemecode
           AND s_old.category = s_new.category
           AND s_old.snapshot_date = :prev_dt
        WHERE s_new.snapshot_date = :cur_dt
          AND s_new.category = :cat
          AND (s_new.rank_in_category - s_old.rank_in_category) <= -3
          AND s_new.rank_in_category <= 30
    """), {"cur_dt": cur_date, "prev_dt": prev_date, "cat": category}).scalar() or 0

    # New top-30 entrants (were outside top 30 before, now inside)
    entrant_count = db.execute(text("""
        SELECT COUNT(*)
        FROM selfmade_ranking_snapshot s_new
        JOIN selfmade_ranking_snapshot s_old
            ON s_old.schemecode = s_new.schemecode
           AND s_old.category = s_new.category
           AND s_old.snapshot_date = :prev_dt
        WHERE s_new.snapshot_date = :cur_dt
          AND s_new.category = :cat
          AND s_new.rank_in_category <= 30
          AND s_old.rank_in_category > 30
    """), {"cur_dt": cur_date, "prev_dt": prev_date, "cat": category}).scalar() or 0

    # Average composite score change
    avg_change = db.execute(text("""
        SELECT AVG(s_new.composite_score_v2 - s_old.composite_score_v2)
        FROM selfmade_ranking_snapshot s_new
        JOIN selfmade_ranking_snapshot s_old
            ON s_old.schemecode = s_new.schemecode
           AND s_old.category = s_new.category
           AND s_old.snapshot_date = :prev_dt
        WHERE s_new.snapshot_date = :cur_dt
          AND s_new.category = :cat
    """), {"cur_dt": cur_date, "prev_dt": prev_date, "cat": category}).scalar()

    return {
        "category": category,
        "has_data": True,
        "current_date": str(cur_date),
        "previous_date": str(prev_date),
        "tiles": [
            {
                "key": "structural_improvers",
                "label": "Structural Improvement Signals",
                "value": int(improver_count),
                "unit": "funds",
                "direction": "positive" if improver_count > 0 else "neutral",
                "description": f"Funds that improved ≥3 ranks into top 30 vs {str(prev_date)}",
            },
            {
                "key": "new_top30_entrants",
                "label": "New Top-30 Entrants",
                "value": int(entrant_count),
                "unit": "funds",
                "direction": "neutral",
                "description": f"Research candidates newly entering the top 30 vs {str(prev_date)}",
            },
            {
                "key": "avg_score_change",
                "label": "Avg Score Change",
                "value": round(float(avg_change), 2) if avg_change is not None else 0.0,
                "unit": "pts",
                "direction": (
                    "positive" if (avg_change or 0) > 0.5
                    else "negative" if (avg_change or 0) < -0.5
                    else "neutral"
                ),
                "description": f"Mean composite score Δ vs {str(prev_date)}",
            },
        ],
        "data_version": settings.data_version,
    }


# ── /rankings/explain/{schemecode} — contribution waterfall ──────────────────

@router.get("/explain/{schemecode}")
def explain_fund_rank(
    schemecode: int,
    category: str = Query(default="Equity — Large Cap"),
    evaluation_date: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    """
    Return score contribution breakdown for a single fund.
    Each component: raw_value, percentile_score (0-100), contribution (pct × weight).
    Total of contributions ≈ composite_score_v2 (within floating-point epsilon).
    """
    if evaluation_date:
        snap_row = db.execute(text("""
            SELECT id, rank_in_category, composite_score_v2, fund_name, snapshot_date
            FROM selfmade_ranking_snapshot
            WHERE category = :cat AND schemecode = :sc
              AND snapshot_date <= :ed::date
            ORDER BY snapshot_date DESC
            LIMIT 1
        """), {"cat": category, "sc": schemecode, "ed": evaluation_date}).fetchone()
    else:
        snap_row = db.execute(text("""
            SELECT id, rank_in_category, composite_score_v2, fund_name, snapshot_date
            FROM selfmade_ranking_snapshot
            WHERE category = :cat AND schemecode = :sc
            ORDER BY snapshot_date DESC
            LIMIT 1
        """), {"cat": category, "sc": schemecode}).fetchone()

    if not snap_row:
        raise HTTPException(
            status_code=404,
            detail=f"No ranking snapshot found for schemecode {schemecode} in {category}",
        )

    snap_id, rank, total_score, fund_name, snap_date = snap_row

    # Total fund count for status label
    total_count = db.execute(text("""
        SELECT COUNT(*) FROM selfmade_ranking_snapshot
        WHERE snapshot_date = :dt AND category = :cat
    """), {"dt": snap_date, "cat": category}).scalar() or 1

    # Contributions
    contrib_rows = db.execute(text("""
        SELECT
            rc.component_id,
            rcomp.component_name,
            rcomp.label_display,
            rcomp.direction,
            rcomp.weight,
            rcomp.data_note,
            rcomp.sort_order,
            rc.raw_value,
            rc.percentile_score,
            rc.contribution
        FROM selfmade_ranking_contribution rc
        JOIN selfmade_rule_component rcomp ON rcomp.id = rc.component_id
        WHERE rc.snapshot_id = :sid
        ORDER BY rcomp.sort_order
    """), {"sid": snap_id}).fetchall()

    components = []
    total_contribution = 0.0
    for row in contrib_rows:
        (cid, cname, label, direction, weight, note, sort_ord,
         raw, pct_score, contrib) = row
        contrib_f = float(contrib or 0)
        total_contribution += contrib_f
        components.append({
            "component_id": cid,
            "component_name": cname,
            "label_display": label or cname,
            "direction": direction,
            "weight": float(weight),
            "data_note": note,
            "raw_value": round(float(raw), 6) if raw is not None else None,
            "percentile_score": round(float(pct_score or 0), 2),
            "contribution": round(contrib_f, 4),
        })

    return {
        "schemecode": schemecode,
        "fund_name": fund_name,
        "category": category,
        "evaluation_date": str(snap_date),
        "rank": rank,
        "total_in_category": total_count,
        "status_label": _status_label(rank, total_count),
        "composite_score": round(float(total_score or 0), 2),
        "contribution_sum": round(total_contribution, 4),
        "rule_version": LATEST_RULE_VERSION,
        "components": components,
        "data_version": settings.data_version,
        "calculation_version": "2.0",
        "confidence": "High" if all(c["raw_value"] is not None for c in components) else "Medium",
    }


# ── /rankings/fund/{scheme_plan_id}/rank-history (legacy compat) ─────────────

@router.get("/fund/{scheme_plan_id}/rank-history")
def fund_rank_history(
    scheme_plan_id: str,
    category: str = Query(default="Equity — Large Cap"),
    db: Session = Depends(get_db),
) -> dict:
    """Rank trajectory for a single fund across all 6 evaluation dates."""
    try:
        sc = int(scheme_plan_id)
    except ValueError:
        return {"scheme_plan_id": scheme_plan_id, "series": []}

    rows = db.execute(text("""
        SELECT snapshot_date, rank_in_category, composite_score_v2
        FROM selfmade_ranking_snapshot
        WHERE schemecode = :sc AND category = :cat
        ORDER BY snapshot_date
    """), {"sc": sc, "cat": category}).fetchall()

    return {
        "scheme_plan_id": scheme_plan_id,
        "category": category,
        "series": [
            {"date": str(r[0]), "rank": r[1], "score": round(float(r[2] or 0), 2)}
            for r in rows
        ],
    }
