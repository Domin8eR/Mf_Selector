"""
Rankings endpoints.

Every endpoint here reads exclusively from the unified, governed pipeline:
selfmade_ranking_snapshot (schemecode, category, composite_score_v2,
rank_in_category, rank_delta_6m) + selfmade_ranking_contribution (per-
component breakdown), both populated by app.rankings.recompute's
recompute_all_rankings() — the one canonical formula, reading whatever
rule version is currently active. category values are real
category_taxonomy_current.bucket_36 leaves (e.g. "Large Cap", "Sectoral
funds") or one of the 3 aggregates ("ALL Equity"/"ALL Hybrid"/"ALL
Passive") or "ALL" (no filter) — see CATEGORY_TAXONOMY below.

selfmade_scheme_ranking (the old, disconnected-from-the-rule-engine table
built by the now-retired scripts/step4_scheme_ranking.py) is no longer
read or written anywhere in this file — left as an inert historical
artifact, not dropped.

/history, /what-changed, /explain, and /fund/{id}/rank-history compare
across snapshot_date for the same category: they only have real trend
once recompute_all_rankings() has run more than once for that category
(each rule approval, or a manual pipeline run, adds one more real data
point) — they degrade to "no data yet" honestly otherwise, not an error.

Scoring: weighted percentile normalization using selfmade_rule_component weights
of whichever selfmade_rule_version is currently active.
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

SORT_BASIS = "RULE_ENGINE_V1"

# ── Category taxonomy — category_taxonomy_current.bucket_36 / bucket_group ────
# This is the real, normalized fund taxonomy (category_taxonomy_mapping, active
# version), not a hand-invented grouping. bucket_36 is the 31 leaf categories;
# bucket_group is the aggregate ("ALL Equity" / "ALL Hybrid" / "ALL Passive")
# each leaf rolls up into. "ALL" is not a taxonomy value — it means no filter.
CATEGORY_TAXONOMY: list[str] = [
    "ALL", "ALL Equity", "ALL Hybrid", "ALL Passive",
    "Large Cap", "Large & Mid Cap", "Flexi Cap", "Multi Cap", "Mid Cap", "Small Cap",
    "ELSS", "Focused Fund", "Value / Contra", "Dividend Yield",
    "Sectoral funds", "Thematic funds", "Index Funds", "ETFs",
    "International Equity", "International ETFs / FoFs", "Market Cap Funds",
    "Low Duration", "Ultra Short Duration", "Overnight funds", "Liquid",
    "Fixed Maturity Plans", "Aggressive Hybrid", "Conservative Hybrid",
    "Balanced Advantage / Dynamic Asset Allocation", "Multi Asset Allocation",
    "Arbitrage", "Equity Savings", "Fund of Funds",
    "Gold ETFs / Gold FoFs", "Silver ETFs / Silver FoFs",
]
_AGGREGATE_CATEGORIES = {"ALL", "ALL Equity", "ALL Hybrid", "ALL Passive"}


def _get_active_rule_version(db: "Session") -> str:
    """Return the version_label of whichever selfmade_rule_version is currently active."""
    from sqlalchemy import text as _text
    row = db.execute(_text(
        "SELECT version_label FROM selfmade_rule_version WHERE is_active = true ORDER BY id DESC LIMIT 1"
    )).fetchone()
    return row[0] if row else "v1.0"


def _status_label(rank: int, total: int) -> str:
    pct = 1.0 - (rank - 1) / max(total, 1)
    for threshold, label in _STATUS_CUTOFFS:
        if pct >= threshold:
            return label
    return "Weak"


def _score_change_window_label(days: int | None) -> str:
    """
    Honest label for whatever real historical window is actually available —
    NEVER hardcode "2Y"/"1Y": selfmade_ranking_snapshot only goes back to
    2026-02-09 under the current RULE_ENGINE_V1 formula (~5 months as of
    2026-07), so a fixed multi-year label would silently misrepresent a
    much shorter real window. Recomputed from real data every request, so
    the label grows honestly (5mo -> 1y -> ...) as more snapshots accrue.
    """
    if not days or days <= 0:
        return "Insufficient history"
    if days < 45:
        return f"{days}d"
    if days < 335:
        return f"{round(days / 30.44)}mo"
    return f"{round(days / 365.25, 1)}y"


_PLAN_LABELS = {5: "Direct", 6: "Regular"}


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

    active_rv = _get_active_rule_version(db)
    return {
        "runs": [
            {
                "run_date": str(r[0]),
                "category": r[1],
                "fund_count": r[2],
                "sort_basis": r[4] or SORT_BASIS,
                "avg_score": round(float(r[3]), 2) if r[3] else None,
                "rule_version": active_rv,
                "calculation_version": "2.0",
            }
            for r in rows
        ],
        "as_of_date": str(date.today()),
        "data_version": settings.data_version,
    }


# ── /rankings/categories — dropdown options with real coverage counts ────────

@router.get("/categories")
def list_ranking_categories(db: Session = Depends(get_db)) -> dict:
    """
    Full 35-value category taxonomy (4 aggregates + 31 real bucket_36 leaves)
    with the real count of currently-ranked schemes in each — so the frontend
    can show a live coverage badge instead of implying every category is
    equally populated.
    """
    rows = db.execute(text("""
        SELECT t.bucket_36, t.bucket_group, COUNT(DISTINCT s.schemecode) AS ranked_count
        FROM category_taxonomy_current t
        LEFT JOIN selfmade_ranking_snapshot s
            ON s.schemecode = t.schemecode AND s.category = t.bucket_36
        WHERE t.bucket_36 IS NOT NULL AND t.bucket_36 <> ''
        GROUP BY t.bucket_36, t.bucket_group
    """)).fetchall()

    counts_by_leaf = {r[0]: int(r[2]) for r in rows}
    group_by_leaf = {r[0]: r[1] for r in rows}
    counts_by_group: dict[str, int] = {}
    for _, group, count in rows:
        if group:
            counts_by_group[group] = counts_by_group.get(group, 0) + int(count)
    total_ranked = sum(counts_by_leaf.values())

    categories = []
    for key in CATEGORY_TAXONOMY:
        if key == "ALL":
            count = total_ranked
        elif key in _AGGREGATE_CATEGORIES:
            count = counts_by_group.get(key, 0)
        else:
            count = counts_by_leaf.get(key, 0)
        categories.append({
            "key": key,
            "is_aggregate": key in _AGGREGATE_CATEGORIES,
            # Real bucket_group this leaf rolls up into (null for aggregates/"ALL")
            "bucket_group": None if key in _AGGREGATE_CATEGORIES else group_by_leaf.get(key),
            "ranked_count": count,
        })

    return {"categories": categories, "data_version": settings.data_version}


# ── /rankings/category ────────────────────────────────────────────────────────

@router.get("/category")
def get_category_rankings(
    category: str = Query(default="Large Cap"),
    evaluation_date: str | None = Query(
        default=None,
        description=(
            "Accepted for backward compatibility; unused. This endpoint always "
            "shows each fund's most recent real snapshot for the requested category."
        ),
    ),
    rule_set_id: str | None = Query(default=None),
    search: str | None = Query(default=None, description="Filter by fund name substring"),
    aum_min_cr: float | None = Query(default=None, description="Minimum AUM in Rs crores"),
    aum_max_cr: float | None = Query(default=None, description="Maximum AUM in Rs crores"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    """
    Return ranked funds for a category (or an ALL / ALL Equity / ALL Hybrid /
    ALL Passive aggregate) from the unified, governed ranking pipeline
    (selfmade_ranking_snapshot, written by recompute_all_rankings()),
    filtered via category_taxonomy_current.bucket_36 / bucket_group.

    For each schemecode matching the taxonomy filter, only its most recent
    real snapshot row for its OWN current bucket_36 category is used (the
    LATERAL join below) — this naturally excludes any stale row stored
    under an old category naming, and naturally excludes schemecodes that
    have never been scored (insufficient data), without needing a separate
    "insufficient data" branch.

    rank_in_category / total_in_category are computed live (RANK() OVER /
    COUNT(*) OVER) within the taxonomy-filtered set, which reproduces the
    stored per-category percentile rank exactly for single-category leaves
    and gives an honest, real rank for aggregate views spanning multiple
    underlying categories (e.g. "Sectoral funds", "ALL Equity").
    """
    if category not in CATEGORY_TAXONOMY:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown category '{category}'. Must be one of: {', '.join(CATEGORY_TAXONOMY)}",
        )

    active_rv = _get_active_rule_version(db)
    as_of_row = db.execute(text("SELECT MAX(snapshot_date) FROM selfmade_ranking_snapshot")).fetchone()
    as_of = as_of_row[0] if as_of_row and as_of_row[0] else date.today()

    if category == "ALL":
        taxonomy_filter = "TRUE"
    elif category in _AGGREGATE_CATEGORIES:
        taxonomy_filter = "t.bucket_group = :category"
    else:
        taxonomy_filter = "t.bucket_36 = :category"

    # aum_cr: latest positive AUM from accord_fintech_mf_portfolio (see
    # get_aum_for_fund in app.insights.calculator for why not scheme_aum —
    # same source, computed inline here to avoid an N+1 query per row).
    search_filter = f"%{search}%" if search else None
    rows = db.execute(text(f"""
        SELECT * FROM (
            SELECT
                s.schemecode,
                s.fund_name,
                RANK() OVER (ORDER BY s.composite_score_v2 DESC) AS rank_in_category,
                COUNT(*) OVER () AS total_in_category,
                s.composite_score_v2 AS composite_score,
                s.snapshot_date AS cur_snapshot_date,
                s.information_ratio_3yr,
                s.rank_delta_6m,
                sm.sharpe_ratio_3yr,
                sm.tracking_error_3yr,
                sm.ir_slope_6m_proxy,
                sr.active_3yr_ret,
                sr.fund_1yr_ret,
                sr.fund_3yr_ret,
                COALESCE(a.s_name, 'Unknown AMC') AS amc_name,
                sd.plan AS plan_code,
                earliest.earliest_score,
                earliest.earliest_date,
                (
                    SELECT (p.aum / 100.0) FROM accord_fintech_mf_portfolio p
                    WHERE p.schemecode = s.schemecode AND p.aum IS NOT NULL AND p.aum > 0
                    ORDER BY p.invdate DESC LIMIT 1
                ) AS aum_cr
            FROM category_taxonomy_current t
            JOIN LATERAL (
                SELECT * FROM selfmade_ranking_snapshot s2
                WHERE s2.schemecode = t.schemecode AND s2.category = t.bucket_36
                ORDER BY s2.snapshot_date DESC LIMIT 1
            ) s ON TRUE
            JOIN selfmade_scheme_metrics sm ON sm.schemecode = s.schemecode
            LEFT JOIN selfmade_scheme_returns sr ON sr.schemecode = s.schemecode
            LEFT JOIN altstreet_scheme_master asm ON asm.scheme_id::integer = s.schemecode
            LEFT JOIN amc_mst_new a ON a.amc_code = asm.amc::integer
            LEFT JOIN accord_fintech_scheme_details sd ON sd.schemecode = s.schemecode
            -- Earliest real snapshot for this schemecode under the CURRENT
            -- formula (RULE_ENGINE_V1), matched by schemecode only — NOT by
            -- category label, because category_taxonomy_current was renamed
            -- partway through (e.g. "Equity — Large Cap" -> "Large Cap") and
            -- a fund's own score history is continuous across that rename.
            -- Funds only present since the rename (no earlier row at all)
            -- correctly get earliest_date = their own single snapshot, i.e.
            -- zero real window -> "insufficient history" below, not a guess.
            LEFT JOIN LATERAL (
                SELECT s3.composite_score_v2 AS earliest_score, s3.snapshot_date AS earliest_date
                FROM selfmade_ranking_snapshot s3
                WHERE s3.schemecode = s.schemecode AND s3.sort_basis = 'RULE_ENGINE_V1'
                ORDER BY s3.snapshot_date ASC LIMIT 1
            ) earliest ON TRUE
            WHERE {taxonomy_filter}
        ) ranked
        WHERE (:aum_min IS NULL OR aum_cr >= :aum_min)
          AND (:aum_max IS NULL OR aum_cr <= :aum_max)
          AND (:search IS NULL OR fund_name ILIKE :search)
        ORDER BY rank_in_category
    """), {
        "category": category,
        "search": search_filter,
        "aum_min": aum_min_cr,
        "aum_max": aum_max_cr,
    }).fetchall()

    total = len(rows)
    start = (page - 1) * page_size
    paged = rows[start: start + page_size]

    # Real window found across the WHOLE category (not just this page), so the
    # column-header label reflects the actual data honestly regardless of
    # which page is being viewed.
    max_window_days = 0
    for r in rows:
        cur_dt, earliest_dt = r[5], r[17]
        if cur_dt and earliest_dt:
            max_window_days = max(max_window_days, (cur_dt - earliest_dt).days)
    score_change_window_label = _score_change_window_label(max_window_days)

    results = []
    for r in paged:
        (sc, name, rank, total_ic, score, cur_dt, ir3, delta6m, sharpe, te, slope,
         active_ret, ret1y, ret3y, amc, plan_code, earliest_score, earliest_dt, aum_cr) = r

        score_change = None
        if earliest_score is not None and earliest_dt and cur_dt and earliest_dt < cur_dt:
            score_change = round(float(score) - float(earliest_score), 2)

        results.append({
            "schemecode": sc,
            "fund_name": name,
            "amc_name": amc,
            "plan_label": _PLAN_LABELS.get(plan_code),
            "rank": int(rank),
            "composite_score": round(float(score or 0), 2),
            "status_label": _status_label(int(rank), total),
            "rank_delta_6m": int(delta6m) if delta6m is not None else None,
            "ir_3yr": round(float(ir3), 4) if ir3 is not None else None,
            "sharpe_3yr": round(float(sharpe), 4) if sharpe is not None else None,
            "tracking_error_3yr": round(float(te), 4) if te is not None else None,
            "ir_slope_6m_proxy": round(float(slope), 6) if slope is not None else None,
            "active_ret_3yr": round(float(active_ret), 4) if active_ret is not None else None,
            "ret_1yr": round(float(ret1y), 4) if ret1y is not None else None,
            "ret_3yr": round(float(ret3y), 4) if ret3y is not None else None,
            "aum_cr": round(float(aum_cr), 2) if aum_cr is not None else None,
            "score_change": score_change,
        })

    return {
        "data_version": settings.data_version,
        "rule_version": active_rv,
        "calculation_version": "2.0",
        "as_of_date": str(as_of),
        "evaluation_date": str(as_of),
        "category": category,
        "sort_basis": SORT_BASIS,
        "total": total,
        "page": page,
        "page_size": page_size,
        "score_change_window_label": score_change_window_label,
        "results": results,
    }


# ── /rankings/history — bump chart data ──────────────────────────────────────

@router.get("/history")
def get_ranking_history(
    category: str = Query(default="Large Cap"),
    top_n: int = Query(default=10, ge=3, le=30, description="Track top-N funds"),
    mode: str = Query(
        default="latest",
        description=(
            "'latest': top-N funds as of the most recent snapshot only "
            "(Rank History bump chart). 'union': union of top-N funds across "
            "EVERY real snapshot date (Score History chart) — naturally more "
            "than N funds if top-N membership shifted between snapshots."
        ),
    ),
    db: Session = Depends(get_db),
) -> dict:
    """
    Return rank + composite_score_v2 history for the top-N funds in a
    category, across every REAL snapshot date that exists for it.

    Matched by schemecode (not raw category-label equality): category_
    taxonomy_current was renamed partway through this build (e.g.
    "Equity — Large Cap" -> "Large Cap"), and a fund's own snapshot history
    is continuous across that rename. Filtering on the literal category
    string here would silently truncate Large/Mid/Small Cap to their single
    most-recent snapshot and hide 6 real months of history — this bit us
    once already in /rankings/category before that endpoint was fixed the
    same way (see Step 2 of the ranking-formula-unification session).

    Categories that only ever existed under the new taxonomy naming (Index
    Funds, Multi Cap, Large & Mid Cap, Thematic funds) correctly have <2
    real dates here — callers must show that honestly, not assume 6+ months
    of history always exists.
    """
    eval_dates_raw = db.execute(text("""
        SELECT DISTINCT s.snapshot_date
        FROM selfmade_ranking_snapshot s
        JOIN category_taxonomy_current t ON t.schemecode = s.schemecode
        WHERE t.bucket_36 = :cat AND s.sort_basis = 'RULE_ENGINE_V1'
        ORDER BY s.snapshot_date
    """), {"cat": category}).fetchall()
    date_list = [str(r[0]) for r in eval_dates_raw]

    if not date_list:
        return {"category": category, "dates": [], "series": []}

    latest_date = date_list[-1]

    if mode == "union":
        code_rows = db.execute(text("""
            SELECT DISTINCT s.schemecode, s.fund_name
            FROM selfmade_ranking_snapshot s
            JOIN category_taxonomy_current t ON t.schemecode = s.schemecode
            WHERE t.bucket_36 = :cat AND s.sort_basis = 'RULE_ENGINE_V1'
              AND s.rank_in_category <= :n
        """), {"cat": category, "n": top_n}).fetchall()
    else:
        code_rows = db.execute(text("""
            SELECT s.schemecode, s.fund_name
            FROM selfmade_ranking_snapshot s
            JOIN category_taxonomy_current t ON t.schemecode = s.schemecode
            WHERE t.bucket_36 = :cat AND s.snapshot_date = :dt
              AND s.sort_basis = 'RULE_ENGINE_V1'
            ORDER BY s.rank_in_category
            LIMIT :n
        """), {"cat": category, "dt": latest_date, "n": top_n}).fetchall()

    if not code_rows:
        return {"category": category, "dates": date_list, "series": []}

    code_set = [r[0] for r in code_rows]
    name_map = {r[0]: r[1] for r in code_rows}

    # For each fund, get its real rank + score at each real date — matched by
    # schemecode only (same rename-proofing as above), no category filter
    # needed here since code_set is already scoped to this category.
    history_rows = db.execute(text("""
        SELECT schemecode, snapshot_date, rank_in_category, composite_score_v2
        FROM selfmade_ranking_snapshot
        WHERE sort_basis = 'RULE_ENGINE_V1' AND schemecode = ANY(:codes)
        ORDER BY schemecode, snapshot_date
    """), {"codes": code_set}).fetchall()

    from collections import defaultdict
    fund_history: dict[int, dict[str, tuple]] = defaultdict(dict)
    for sc, dt, rank, score in history_rows:
        fund_history[sc][str(dt)] = (rank, float(score) if score is not None else None)

    series = []
    for sc in code_set:
        by_date = fund_history.get(sc, {})
        data_points = [
            {
                "date": d,
                "rank": by_date[d][0] if d in by_date else None,
                "composite_score": round(by_date[d][1], 2) if d in by_date and by_date[d][1] is not None else None,
            }
            for d in date_list
        ]
        latest_rank = by_date[latest_date][0] if latest_date in by_date else None
        series.append({
            "schemecode": sc,
            "fund_name": name_map.get(sc, str(sc)),
            "latest_rank": latest_rank,
            "data": data_points,
        })

    # Funds still ranked as of the latest date sort first (by rank); funds
    # that dropped out of top-N by the latest date (union mode only) sort
    # after, so the legend reads top-to-bottom by current standing.
    series.sort(key=lambda s: (s["latest_rank"] is None, s["latest_rank"] or 0))

    return {
        "category": category,
        "mode": mode,
        "dates": date_list,
        "series": series,
        "as_of_date": str(latest_date),
        "data_version": settings.data_version,
    }


# ── /rankings/what-changed — 3 KPI tiles ─────────────────────────────────────

@router.get("/what-changed")
def get_what_changed(
    category: str = Query(default="Large Cap"),
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
    category: str = Query(default="Large Cap"),
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

    # Contributions — scoped to the CURRENTLY ACTIVE rule version's
    # components only. Every rule version recompute_all_rankings() has ever
    # run for produces its own component_id set (no FK collision across
    # versions), so a snapshot row accumulates one contribution row per
    # component PER VERSION that ever scored it — without this filter,
    # explain would mix old and new weights for the same fund.
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
        JOIN selfmade_rule_version rv ON rv.id = rcomp.rule_version_id AND rv.is_active = true
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
        "rule_version": _get_active_rule_version(db),
        "components": components,
        "data_version": settings.data_version,
        "calculation_version": "2.0",
        "confidence": "High" if all(c["raw_value"] is not None for c in components) else "Medium",
    }


# ── /rankings/fund/{scheme_plan_id}/rank-history (legacy compat) ─────────────

@router.get("/fund/{scheme_plan_id}/rank-history")
def fund_rank_history(
    scheme_plan_id: str,
    category: str = Query(default="Large Cap"),
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
