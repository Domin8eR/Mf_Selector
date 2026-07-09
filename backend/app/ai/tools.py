"""Allow-listed tool registry for the AltStreet AI layer.

Every function reads from internal validated selfmade_* tables.
No vendor API is called at request time.
Every invocation is logged to tool_call_log.

AI does NOT compute metrics — it only retrieves pre-computed results.
"""

from __future__ import annotations

import time
import uuid as _uuid
from typing import Any

from sqlalchemy.orm import Session

# ── Allow-list (exact names LLM may request) ──────────────────────────────────

ALLOWED_TOOLS: set[str] = {
    "get_category_rankings",
    "get_fund_metrics",
    "get_rank_history",
    "get_growth_of_10k",
    "get_rolling_ir",
    "get_consistency_heatmap",
    "get_benchmark_comparison",
    "get_rankings_explain",
    "get_rankings_what_changed",
    "compare_funds",
    "get_holdings",
    "get_current_rules",
    "search_documents",
}


def _log_call(
    db: Session,
    tool_name: str,
    input_json: dict,
    output_json: dict | None,
    latency_ms: int,
    status: str,
    error: str | None = None,
    thread_id: str | None = None,
) -> None:
    from app.models.chat import ToolCallLog
    tid = _uuid.UUID(thread_id) if thread_id else None
    db.add(ToolCallLog(
        thread_id=tid,
        tool_name=tool_name,
        input_json=input_json,
        output_json=output_json,
        latency_ms=latency_ms,
        status=status,
        error_detail=error,
        # message_id left NULL — router backfills after assistant message is saved
    ))
    db.flush()


def call_tool(
    tool_name: str,
    params: dict[str, Any],
    db: Session,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """Dispatch a tool call by name, enforce allow-list, log every call."""
    if tool_name not in ALLOWED_TOOLS:
        raise ValueError(f"Tool '{tool_name}' is not on the allow-list")

    t0 = time.monotonic()
    result: dict[str, Any] = {}
    error: str | None = None
    status = "ok"

    try:
        result = _REGISTRY[tool_name](params, db)
    except Exception as exc:
        status = "error"
        error = str(exc)
        result = {"error": error}
    finally:
        latency = int((time.monotonic() - t0) * 1000)
        _log_call(db, tool_name, params, result, latency, status, error, thread_id)

    return result


# ── Tool implementations ──────────────────────────────────────────────────────


def _get_category_rankings(params: dict, db: Session) -> dict:
    """Return top-ranked funds for a category from the latest snapshot."""
    from sqlalchemy import text

    category = params.get("category", "Equity — Large Cap")
    limit = min(int(params.get("limit", 10)), 30)

    rows = db.execute(
        text(
            "SELECT schemecode, fund_name, rank_in_category, composite_score, "
            "       composite_score_v2, information_ratio_3yr, rank_delta_6m, snapshot_date "
            "FROM selfmade_ranking_snapshot "
            "WHERE category = :cat "
            "  AND snapshot_date = (SELECT MAX(snapshot_date) FROM selfmade_ranking_snapshot "
            "                       WHERE category = :cat) "
            "ORDER BY rank_in_category "
            "LIMIT :lim"
        ),
        {"cat": category, "lim": limit},
    ).fetchall()

    return {
        "category": category,
        "snapshot_date": str(rows[0][7]) if rows else None,
        "source_table": "selfmade_ranking_snapshot",
        "funds": [
            {
                "schemecode": r[0],
                "fund_name": r[1],
                "rank": r[2],
                "composite_score": float(r[3]) if r[3] is not None else None,
                "composite_score_v2": float(r[4]) if r[4] is not None else None,
                "ir_3yr": float(r[5]) if r[5] is not None else None,
                "rank_delta_6m": int(r[6]) if r[6] is not None else None,
            }
            for r in rows
        ],
    }


def _get_fund_metrics(params: dict, db: Session) -> dict:
    """Return all metrics for a fund by schemecode."""
    from sqlalchemy import text

    schemecode = int(params.get("schemecode", 0))

    metrics_row = db.execute(
        text(
            "SELECT schemecode, category, benchmark_index, as_of_date, "
            "       information_ratio_3yr, jensens_alpha_3yr, sharpe_ratio_3yr, "
            "       sortino_ratio_3yr, tracking_error_3yr, "
            "       outperformed_1yr, outperformed_3yr, outperformed_5yr, "
            "       ir_slope_6m_proxy, is_fallback_benchmark "
            "FROM selfmade_scheme_metrics WHERE schemecode = :sc"
        ),
        {"sc": schemecode},
    ).fetchone()

    returns_row = db.execute(
        text(
            "SELECT as_of_date, fund_1yr_ret, fund_3yr_ret, fund_5yr_ret, "
            "       bm_1yr_ret, bm_3yr_ret, bm_5yr_ret, "
            "       active_1yr_ret, active_3yr_ret, active_5yr_ret "
            "FROM selfmade_scheme_returns WHERE schemecode = :sc"
        ),
        {"sc": schemecode},
    ).fetchone()

    name_row = db.execute(
        text(
            "SELECT fund_name FROM selfmade_ranking_snapshot "
            "WHERE schemecode = :sc ORDER BY snapshot_date DESC LIMIT 1"
        ),
        {"sc": schemecode},
    ).fetchone()

    if not metrics_row and not returns_row:
        return {"error": f"No metrics found for schemecode {schemecode}"}

    result: dict = {
        "schemecode": schemecode,
        "fund_name": name_row[0] if name_row else str(schemecode),
        "source_tables": ["selfmade_scheme_metrics", "selfmade_scheme_returns"],
    }

    if metrics_row:
        result["metrics"] = {
            "category": metrics_row[1],
            "benchmark": metrics_row[2],
            "as_of_date": str(metrics_row[3]) if metrics_row[3] else None,
            "information_ratio_3yr": float(metrics_row[4]) if metrics_row[4] is not None else None,
            "jensens_alpha_3yr": float(metrics_row[5]) if metrics_row[5] is not None else None,
            "sharpe_ratio_3yr": float(metrics_row[6]) if metrics_row[6] is not None else None,
            "sortino_ratio_3yr": float(metrics_row[7]) if metrics_row[7] is not None else None,
            "tracking_error_3yr": float(metrics_row[8]) if metrics_row[8] is not None else None,
            "outperformed_1yr": bool(metrics_row[9]) if metrics_row[9] is not None else None,
            "outperformed_3yr": bool(metrics_row[10]) if metrics_row[10] is not None else None,
            "outperformed_5yr": bool(metrics_row[11]) if metrics_row[11] is not None else None,
            "ir_slope_6m_proxy": float(metrics_row[12]) if metrics_row[12] is not None else None,
            "is_fallback_benchmark": bool(metrics_row[13]),
        }

    if returns_row:
        result["returns"] = {
            "as_of_date": str(returns_row[0]) if returns_row[0] else None,
            "fund_1yr": float(returns_row[1]) if returns_row[1] is not None else None,
            "fund_3yr": float(returns_row[2]) if returns_row[2] is not None else None,
            "fund_5yr": float(returns_row[3]) if returns_row[3] is not None else None,
            "bm_1yr": float(returns_row[4]) if returns_row[4] is not None else None,
            "bm_3yr": float(returns_row[5]) if returns_row[5] is not None else None,
            "bm_5yr": float(returns_row[6]) if returns_row[6] is not None else None,
            "active_1yr": float(returns_row[7]) if returns_row[7] is not None else None,
            "active_3yr": float(returns_row[8]) if returns_row[8] is not None else None,
            "active_5yr": float(returns_row[9]) if returns_row[9] is not None else None,
        }

    return result


def _get_rankings_explain(params: dict, db: Session) -> dict:
    """Explain why a fund ranks where it does — contribution breakdown."""
    from sqlalchemy import text

    schemecode = int(params.get("schemecode", 0))
    category = params.get("category", "Equity — Large Cap")

    snapshot_row = db.execute(
        text(
            "SELECT id, rank_in_category, composite_score_v2, snapshot_date, fund_name "
            "FROM selfmade_ranking_snapshot "
            "WHERE schemecode = :sc AND category = :cat "
            "ORDER BY snapshot_date DESC LIMIT 1"
        ),
        {"sc": schemecode, "cat": category},
    ).fetchone()

    if not snapshot_row:
        return {"error": f"No ranking snapshot found for schemecode {schemecode} in {category}"}

    snap_id, rank, score, snap_date, fund_name = snapshot_row

    contributions = db.execute(
        text(
            "SELECT rc.component_name, rc.label_display, rc.weight, rc.direction, "
            "       src.raw_value, src.percentile_score, src.contribution "
            "FROM selfmade_ranking_contribution src "
            "JOIN selfmade_rule_component rc ON rc.id = src.component_id "
            "WHERE src.snapshot_id = :sid "
            "ORDER BY rc.sort_order"
        ),
        {"sid": snap_id},
    ).fetchall()

    return {
        "schemecode": schemecode,
        "fund_name": fund_name,
        "category": category,
        "rank": rank,
        "composite_score": float(score) if score else None,
        "snapshot_date": str(snap_date),
        "source_tables": ["selfmade_ranking_snapshot", "selfmade_ranking_contribution", "selfmade_rule_component"],
        "contributions": [
            {
                "component": r[0],
                "label": r[1] or r[0],
                "weight_pct": round(float(r[2]) * 100, 1) if r[2] else None,
                "direction": r[3],
                "raw_value": float(r[4]) if r[4] is not None else None,
                "percentile": float(r[5]) if r[5] is not None else None,
                "contribution": float(r[6]) if r[6] is not None else None,
            }
            for r in contributions
        ],
    }


def _get_rankings_what_changed(params: dict, db: Session) -> dict:
    """Return funds with the biggest rank movement in the last 6 months."""
    from sqlalchemy import text

    category = params.get("category", "Equity — Large Cap")
    limit = min(int(params.get("limit", 10)), 20)

    rows = db.execute(
        text(
            "SELECT schemecode, fund_name, rank_in_category, rank_delta_6m, "
            "       composite_score_v2, snapshot_date "
            "FROM selfmade_ranking_snapshot "
            "WHERE category = :cat "
            "  AND snapshot_date = (SELECT MAX(snapshot_date) FROM selfmade_ranking_snapshot "
            "                       WHERE category = :cat) "
            "  AND rank_delta_6m IS NOT NULL "
            "ORDER BY ABS(rank_delta_6m) DESC "
            "LIMIT :lim"
        ),
        {"cat": category, "lim": limit},
    ).fetchall()

    return {
        "category": category,
        "source_table": "selfmade_ranking_snapshot",
        "movers": [
            {
                "schemecode": r[0],
                "fund_name": r[1],
                "current_rank": r[2],
                "rank_delta_6m": int(r[3]) if r[3] is not None else None,
                "direction": "improved" if (r[3] or 0) < 0 else "declined",
                "composite_score": float(r[4]) if r[4] is not None else None,
                "snapshot_date": str(r[5]),
            }
            for r in rows
        ],
    }


def _compare_funds(params: dict, db: Session) -> dict:
    """Compare multiple funds side-by-side on metrics and returns."""
    from sqlalchemy import text

    schemecodes: list[int] = [int(s) for s in params.get("schemecodes", [])]
    if len(schemecodes) < 2:
        return {"error": "compare_funds requires at least 2 schemecodes"}
    if len(schemecodes) > 5:
        schemecodes = schemecodes[:5]

    placeholders = ", ".join(f":sc{i}" for i in range(len(schemecodes)))
    sc_params = {f"sc{i}": sc for i, sc in enumerate(schemecodes)}

    metrics_rows = db.execute(
        text(
            f"SELECT schemecode, information_ratio_3yr, sharpe_ratio_3yr, "
            f"       jensens_alpha_3yr, sortino_ratio_3yr, tracking_error_3yr, "
            f"       outperformed_3yr, ir_slope_6m_proxy, as_of_date "
            f"FROM selfmade_scheme_metrics WHERE schemecode IN ({placeholders})"
        ),
        sc_params,
    ).fetchall()

    returns_rows = db.execute(
        text(
            f"SELECT schemecode, fund_1yr_ret, fund_3yr_ret, fund_5yr_ret, "
            f"       active_1yr_ret, active_3yr_ret "
            f"FROM selfmade_scheme_returns WHERE schemecode IN ({placeholders})"
        ),
        sc_params,
    ).fetchall()

    name_rows = db.execute(
        text(
            f"SELECT DISTINCT ON (schemecode) schemecode, fund_name "
            f"FROM selfmade_ranking_snapshot "
            f"WHERE schemecode IN ({placeholders}) "
            f"ORDER BY schemecode, snapshot_date DESC"
        ),
        sc_params,
    ).fetchall()

    names = {r[0]: r[1] for r in name_rows}
    metrics_map = {r[0]: r for r in metrics_rows}
    returns_map = {r[0]: r for r in returns_rows}

    funds = []
    for sc in schemecodes:
        m = metrics_map.get(sc)
        ret = returns_map.get(sc)
        entry: dict = {
            "schemecode": sc,
            "fund_name": names.get(sc, str(sc)),
        }
        if m:
            entry["ir_3yr"] = float(m[1]) if m[1] is not None else None
            entry["sharpe_3yr"] = float(m[2]) if m[2] is not None else None
            entry["alpha_3yr"] = float(m[3]) if m[3] is not None else None
            entry["sortino_3yr"] = float(m[4]) if m[4] is not None else None
            entry["tracking_error"] = float(m[5]) if m[5] is not None else None
            entry["outperformed_3yr"] = bool(m[6]) if m[6] is not None else None
            entry["ir_slope"] = float(m[7]) if m[7] is not None else None
            entry["as_of_date"] = str(m[8]) if m[8] else None
        if ret:
            entry["fund_1yr"] = float(ret[1]) if ret[1] is not None else None
            entry["fund_3yr"] = float(ret[2]) if ret[2] is not None else None
            entry["fund_5yr"] = float(ret[3]) if ret[3] is not None else None
            entry["active_1yr"] = float(ret[4]) if ret[4] is not None else None
            entry["active_3yr"] = float(ret[5]) if ret[5] is not None else None
        funds.append(entry)

    return {
        "source_tables": ["selfmade_scheme_metrics", "selfmade_scheme_returns"],
        "funds": funds,
    }


def _get_holdings(params: dict, db: Session) -> dict:
    """Return top portfolio holdings for a fund by schemecode."""
    from sqlalchemy import text

    schemecode = int(params.get("schemecode", 0))
    top_n = min(int(params.get("top_n", 10)), 30)

    date_row = db.execute(
        text(
            "SELECT MAX(as_of_date) FROM selfmade_portfolio_holding "
            "WHERE scheme_id = :sc"
        ),
        {"sc": schemecode},
    ).fetchone()

    if not date_row or not date_row[0]:
        return {"error": f"No holdings found for schemecode {schemecode}"}

    as_of_date = date_row[0]

    rows = db.execute(
        text(
            "SELECT sm.company_name, sm.sector, sm.market_cap_bucket, "
            "       ph.holding_weight_pct "
            "FROM selfmade_portfolio_holding ph "
            "JOIN selfmade_security_master sm ON sm.id = ph.security_id "
            "WHERE ph.scheme_id = :sc AND ph.as_of_date = :d "
            "ORDER BY ph.holding_weight_pct DESC "
            "LIMIT :n"
        ),
        {"sc": schemecode, "d": as_of_date, "n": top_n},
    ).fetchall()

    name_row = db.execute(
        text(
            "SELECT fund_name FROM selfmade_ranking_snapshot "
            "WHERE schemecode = :sc ORDER BY snapshot_date DESC LIMIT 1"
        ),
        {"sc": schemecode},
    ).fetchone()

    return {
        "schemecode": schemecode,
        "fund_name": name_row[0] if name_row else str(schemecode),
        "as_of_date": str(as_of_date),
        "source_tables": ["selfmade_portfolio_holding", "selfmade_security_master"],
        "holdings": [
            {
                "company": r[0],
                "sector": r[1],
                "market_cap": r[2],
                "weight_pct": float(r[3]),
            }
            for r in rows
        ],
    }


def _get_current_rules(params: dict, db: Session) -> dict:
    """Return the active rule set components and weights."""
    from sqlalchemy import text

    rows = db.execute(
        text(
            "SELECT rc.component_name, rc.label_display, rc.weight, rc.direction, "
            "       rc.data_note, rv.version_label, rs.name "
            "FROM selfmade_rule_component rc "
            "JOIN selfmade_rule_version rv ON rv.id = rc.rule_version_id "
            "JOIN selfmade_rule_set rs ON rs.id = rv.rule_set_id "
            "WHERE rv.is_active = TRUE "
            "ORDER BY rc.sort_order"
        ),
    ).fetchall()

    if not rows:
        return {"error": "No active rule set found"}

    return {
        "rule_set": rows[0][6] if rows else "Default",
        "version_label": rows[0][5] if rows else "v1",
        "source_table": "selfmade_rule_component",
        "components": [
            {
                "name": r[0],
                "label": r[1] or r[0],
                "weight_pct": round(float(r[2]) * 100, 1) if r[2] else None,
                "direction": r[3],
                "note": r[4],
            }
            for r in rows
        ],
    }


def _get_rank_history(params: dict, db: Session) -> dict:
    """Return rank and 3Y IR over time for a fund from selfmade_ranking_snapshot."""
    from sqlalchemy import text

    schemecode = int(params.get("schemecode", 0))
    category = params.get("category", "Equity — Large Cap")

    rows = db.execute(
        text(
            "SELECT snapshot_date, rank_in_category, composite_score_v2, "
            "       information_ratio_3yr, rank_delta_6m "
            "FROM selfmade_ranking_snapshot "
            "WHERE schemecode = :sc AND category = :cat "
            "ORDER BY snapshot_date"
        ),
        {"sc": schemecode, "cat": category},
    ).fetchall()

    if not rows:
        # Try without category filter — fund may have moved categories
        rows = db.execute(
            text(
                "SELECT snapshot_date, rank_in_category, composite_score_v2, "
                "       information_ratio_3yr, rank_delta_6m "
                "FROM selfmade_ranking_snapshot "
                "WHERE schemecode = :sc "
                "ORDER BY snapshot_date"
            ),
            {"sc": schemecode},
        ).fetchall()

    name_row = db.execute(
        text(
            "SELECT fund_name FROM selfmade_ranking_snapshot "
            "WHERE schemecode = :sc ORDER BY snapshot_date DESC LIMIT 1"
        ),
        {"sc": schemecode},
    ).fetchone()

    if not rows:
        return {"error": f"No rank history found for schemecode {schemecode}"}

    return {
        "schemecode": schemecode,
        "fund_name": name_row[0] if name_row else str(schemecode),
        "source_table": "selfmade_ranking_snapshot",
        "data_points": len(rows),
        "series": [
            {
                "date": str(r[0]),
                "rank": int(r[1]) if r[1] is not None else None,
                "composite_score": float(r[2]) if r[2] is not None else None,
                "ir_3yr": float(r[3]) if r[3] is not None else None,
                "rank_delta": int(r[4]) if r[4] is not None else None,
            }
            for r in rows
        ],
    }


def _get_growth_of_10k(params: dict, db: Session) -> dict:
    """
    Return growth-of-10k series from accord_fintech NAV anchor points.

    Uses the 1yr/2yr/3yr/5yr NAV anchors to compute what ₹10,000 invested
    N years ago would be worth today. Also includes benchmark return for
    the same periods from selfmade_scheme_returns.
    """
    from sqlalchemy import text

    schemecode = int(params.get("schemecode", 0))

    af_row = db.execute(
        text(
            "SELECT c_date, c_nav, "
            "       \"1yrnav\", \"1yrdate\", "
            "       \"3yrnav\", \"3yrdate\", "
            "       \"5yrnav\", \"5yrdate\" "
            "FROM accord_fintech_mf_returns WHERE schemecode = :sc"
        ),
        {"sc": schemecode},
    ).fetchone()

    ret_row = db.execute(
        text(
            "SELECT fund_1yr_ret, fund_3yr_ret, fund_5yr_ret, "
            "       bm_1yr_ret, bm_3yr_ret, bm_5yr_ret "
            "FROM selfmade_scheme_returns WHERE schemecode = :sc"
        ),
        {"sc": schemecode},
    ).fetchone()

    name_row = db.execute(
        text(
            "SELECT fund_name FROM selfmade_ranking_snapshot "
            "WHERE schemecode = :sc ORDER BY snapshot_date DESC LIMIT 1"
        ),
        {"sc": schemecode},
    ).fetchone()

    if not af_row:
        return {"error": f"No NAV anchor data found for schemecode {schemecode}"}

    c_date, c_nav = af_row[0], float(af_row[1]) if af_row[1] else None

    series = []
    if af_row[2] and c_nav:
        nav_1yr = float(af_row[2])
        if nav_1yr > 0:
            series.append({
                "label": "1Y ago → today",
                "anchor_date": str(af_row[3])[:10] if af_row[3] else None,
                "end_date": str(c_date)[:10] if c_date else None,
                "fund_value": round(10000 * c_nav / nav_1yr, 2),
                "bm_value": round(10000 * (1 + float(ret_row[3]) / 100), 2) if ret_row and ret_row[3] else None,
            })
    if af_row[4] and c_nav:
        nav_3yr = float(af_row[4])
        if nav_3yr > 0:
            series.append({
                "label": "3Y ago → today",
                "anchor_date": str(af_row[5])[:10] if af_row[5] else None,
                "end_date": str(c_date)[:10] if c_date else None,
                "fund_value": round(10000 * c_nav / nav_3yr, 2),
                "bm_value": round(10000 * (1 + float(ret_row[4]) / 100) ** 3, 2) if ret_row and ret_row[4] else None,
            })
    if af_row[6] and c_nav:
        nav_5yr = float(af_row[6])
        if nav_5yr > 0:
            series.append({
                "label": "5Y ago → today",
                "anchor_date": str(af_row[7])[:10] if af_row[7] else None,
                "end_date": str(c_date)[:10] if c_date else None,
                "fund_value": round(10000 * c_nav / nav_5yr, 2),
                "bm_value": round(10000 * (1 + float(ret_row[5]) / 100) ** 5, 2) if ret_row and ret_row[5] else None,
            })

    if not series:
        return {"error": "Insufficient NAV anchor data for growth-of-10k calculation"}

    return {
        "schemecode": schemecode,
        "fund_name": name_row[0] if name_row else str(schemecode),
        "base_investment": 10000,
        "currency": "INR",
        "source_tables": ["accord_fintech_mf_returns", "selfmade_scheme_returns"],
        "note": "Values computed from NAV anchor snapshots. fund_value = ₹10,000 × (current_NAV / anchor_NAV). bm_value uses annualised benchmark returns.",
        "series": series,
    }


def _get_rolling_ir(params: dict, db: Session) -> dict:
    """Return rolling IR history from ranking snapshots plus baseline trend signal."""
    from sqlalchemy import text

    schemecode = int(params.get("schemecode", 0))

    snap_rows = db.execute(
        text(
            "SELECT snapshot_date, information_ratio_3yr, rank_in_category "
            "FROM selfmade_ranking_snapshot "
            "WHERE schemecode = :sc AND information_ratio_3yr IS NOT NULL "
            "ORDER BY snapshot_date"
        ),
        {"sc": schemecode},
    ).fetchall()

    ir_row = db.execute(
        text(
            "SELECT information_ratio_3yr, tracking_error_3yr, ir_slope_6m_proxy "
            "FROM selfmade_scheme_metrics WHERE schemecode = :sc"
        ),
        {"sc": schemecode},
    ).fetchone()

    name_row = db.execute(
        text(
            "SELECT fund_name FROM selfmade_ranking_snapshot "
            "WHERE schemecode = :sc ORDER BY snapshot_date DESC LIMIT 1"
        ),
        {"sc": schemecode},
    ).fetchone()

    if not snap_rows and not ir_row:
        return {"error": f"No rolling IR data found for schemecode {schemecode}"}

    series = [
        {
            "date": str(r[0]),
            "ir_3yr": round(float(r[1]), 4),
            "rank": int(r[2]) if r[2] is not None else None,
        }
        for r in snap_rows
    ]

    trend = "insufficient_data"
    if len(series) >= 2:
        delta = series[-1]["ir_3yr"] - series[0]["ir_3yr"]
        trend = "improving" if delta > 0.05 else ("declining" if delta < -0.05 else "stable")

    return {
        "schemecode": schemecode,
        "fund_name": name_row[0] if name_row else str(schemecode),
        "source_table": "selfmade_ranking_snapshot",
        "data_points": len(series),
        "ir_baseline_3yr": float(ir_row[0]) if ir_row and ir_row[0] is not None else None,
        "tracking_error_3yr": float(ir_row[1]) if ir_row and ir_row[1] is not None else None,
        "ir_slope_6m": float(ir_row[2]) if ir_row and ir_row[2] is not None else None,
        "trend": trend,
        "series": series,
        "data_note": (
            "IR values are 3Y rolling IR from ranking snapshots (up to 6 monthly points). "
            "ir_slope_6m is a 6-month linear regression slope from selfmade_scheme_metrics."
        ),
    }


def _get_consistency_heatmap(params: dict, db: Session) -> dict:
    """Summarise the 36-cell monthly IR consistency heatmap for a fund."""
    from sqlalchemy import text

    schemecode = int(params.get("schemecode", 0))

    snap_rows = db.execute(
        text(
            "SELECT snapshot_date, information_ratio_3yr "
            "FROM selfmade_ranking_snapshot "
            "WHERE schemecode = :sc AND information_ratio_3yr IS NOT NULL "
            "ORDER BY snapshot_date"
        ),
        {"sc": schemecode},
    ).fetchall()

    ir_row = db.execute(
        text(
            "SELECT information_ratio_3yr, tracking_error_3yr "
            "FROM selfmade_scheme_metrics WHERE schemecode = :sc"
        ),
        {"sc": schemecode},
    ).fetchone()

    name_row = db.execute(
        text(
            "SELECT fund_name FROM selfmade_ranking_snapshot "
            "WHERE schemecode = :sc ORDER BY snapshot_date DESC LIMIT 1"
        ),
        {"sc": schemecode},
    ).fetchone()

    if not snap_rows and not ir_row:
        return {"error": f"No consistency heatmap data for schemecode {schemecode}"}

    ir_baseline = float(ir_row[0]) if ir_row and ir_row[0] is not None else 0.0
    snapshot_irs = [float(r[1]) for r in snap_rows]
    green = sum(1 for v in snapshot_irs if v >= 0.3)
    yellow = sum(1 for v in snapshot_irs if 0.0 <= v < 0.3)
    red = sum(1 for v in snapshot_irs if v < 0.0)
    n = max(len(snapshot_irs), 1)

    return {
        "schemecode": schemecode,
        "fund_name": name_row[0] if name_row else str(schemecode),
        "source_tables": ["selfmade_ranking_snapshot", "selfmade_scheme_metrics"],
        "heatmap_total_cells": 36,
        "real_snapshot_cells": len(snapshot_irs),
        "ir_baseline_3yr": ir_baseline,
        "tracking_error_3yr": float(ir_row[1]) if ir_row and ir_row[1] is not None else None,
        "snapshot_ir_series": [
            {"date": str(r[0]), "ir": round(float(r[1]), 4)}
            for r in snap_rows
        ],
        "color_summary": {
            "green_cells": green,
            "green_pct": round(green / n * 100, 1),
            "yellow_cells": yellow,
            "yellow_pct": round(yellow / n * 100, 1),
            "red_cells": red,
            "red_pct": round(red / n * 100, 1),
        },
        "interpretation": (
            "green = IR ≥ 0.3 (consistent benchmark outperformance); "
            "yellow = IR 0–0.3 (modest outperformance); "
            "red = IR < 0 (benchmark underperformance). "
            "color_summary reflects the 6 real snapshot values; "
            "remaining 30 of 36 cells are model-estimated from annual NAV anchor segments."
        ),
    }


def _get_benchmark_comparison(params: dict, db: Session) -> dict:
    """Return fund vs benchmark CAGR comparison with excess returns and risk metrics."""
    from sqlalchemy import text

    schemecode = int(params.get("schemecode", 0))

    sr = db.execute(
        text(
            "SELECT fund_1yr_ret, fund_3yr_ret, fund_5yr_ret, "
            "       bm_1yr_ret, bm_3yr_ret, bm_5yr_ret, benchmark_index "
            "FROM selfmade_scheme_returns WHERE schemecode = :sc"
        ),
        {"sc": schemecode},
    ).fetchone()

    sm = db.execute(
        text(
            "SELECT information_ratio_3yr, sharpe_ratio_3yr, tracking_error_3yr, "
            "       jensens_alpha_3yr, outperformed_1yr, outperformed_3yr "
            "FROM selfmade_scheme_metrics WHERE schemecode = :sc"
        ),
        {"sc": schemecode},
    ).fetchone()

    bm_row = db.execute(
        text(
            "SELECT benchmark_index FROM selfmade_scheme_category_benchmark "
            "WHERE schemecode = :sc ORDER BY valid_from DESC LIMIT 1"
        ),
        {"sc": schemecode},
    ).fetchone()

    name_row = db.execute(
        text(
            "SELECT fund_name FROM selfmade_ranking_snapshot "
            "WHERE schemecode = :sc ORDER BY snapshot_date DESC LIMIT 1"
        ),
        {"sc": schemecode},
    ).fetchone()

    if not sr and not sm:
        return {"error": f"No benchmark comparison data for schemecode {schemecode}"}

    bm_name = bm_row[0] if bm_row else (sr[6] if sr and sr[6] else "Benchmark")

    def _bm_cagr(total_ret_frac: float | None, years: float) -> float | None:
        if total_ret_frac is None:
            return None
        return round(((1 + total_ret_frac) ** (1 / years) - 1) * 100, 2)

    fund_1y = round(float(sr[0]), 2) if sr and sr[0] is not None else None
    fund_3y = round(float(sr[1]), 2) if sr and sr[1] is not None else None
    fund_5y = round(float(sr[2]), 2) if sr and sr[2] is not None else None
    bm_1y = _bm_cagr(float(sr[3]) if sr and sr[3] is not None else None, 1.0)
    bm_3y = _bm_cagr(float(sr[4]) if sr and sr[4] is not None else None, 3.0)
    bm_5y = _bm_cagr(float(sr[5]) if sr and sr[5] is not None else None, 5.0)

    def _excess(f: float | None, b: float | None) -> float | None:
        return round(f - b, 2) if f is not None and b is not None else None

    return {
        "schemecode": schemecode,
        "fund_name": name_row[0] if name_row else str(schemecode),
        "benchmark_name": bm_name,
        "source_tables": ["selfmade_scheme_returns", "selfmade_scheme_metrics",
                          "selfmade_scheme_category_benchmark"],
        "returns": {
            "fund_1yr_pct": fund_1y,
            "fund_3yr_pct": fund_3y,
            "fund_5yr_pct": fund_5y,
            "benchmark_1yr_pct": bm_1y,
            "benchmark_3yr_pct": bm_3y,
            "benchmark_5yr_pct": bm_5y,
            "excess_1yr_pct": _excess(fund_1y, bm_1y),
            "excess_3yr_pct": _excess(fund_3y, bm_3y),
            "excess_5yr_pct": _excess(fund_5y, bm_5y),
        },
        "risk_metrics": {
            "information_ratio_3yr": float(sm[0]) if sm and sm[0] is not None else None,
            "sharpe_ratio_3yr": float(sm[1]) if sm and sm[1] is not None else None,
            "tracking_error_3yr": float(sm[2]) if sm and sm[2] is not None else None,
            "alpha_3yr": float(sm[3]) if sm and sm[3] is not None else None,
            "outperformed_1yr": bool(sm[4]) if sm and sm[4] is not None else None,
            "outperformed_3yr": bool(sm[5]) if sm and sm[5] is not None else None,
        },
        "data_note": (
            "bm_*yr_ret converted from total-return fraction to CAGR %. "
            "excess_*yr = fund_*yr_pct − benchmark_*yr_pct (percentage points). "
            "alpha_3yr = jensens_alpha_3yr from selfmade_scheme_metrics."
        ),
    }


def _search_documents(params: dict, db: Session) -> dict:
    """Semantic search over fund factsheets and scheme documents."""
    from app.ai.rag import search_documents

    query = params.get("query", "")
    schemecode = params.get("schemecode")
    top_k = min(int(params.get("top_k", 5)), 10)

    if not query:
        return {"error": "query parameter is required"}

    chunks = search_documents(
        query=query,
        db=db,
        scheme_id=int(schemecode) if schemecode else None,
        top_k=top_k,
    )

    return {
        "query": query,
        "source_table": "selfmade_document_chunk",
        "result_count": len(chunks),
        "chunks": chunks,
    }


_REGISTRY: dict[str, Any] = {
    "get_category_rankings": _get_category_rankings,
    "get_fund_metrics": _get_fund_metrics,
    "get_rank_history": _get_rank_history,
    "get_growth_of_10k": _get_growth_of_10k,
    "get_rolling_ir": _get_rolling_ir,
    "get_consistency_heatmap": _get_consistency_heatmap,
    "get_benchmark_comparison": _get_benchmark_comparison,
    "get_rankings_explain": _get_rankings_explain,
    "get_rankings_what_changed": _get_rankings_what_changed,
    "compare_funds": _compare_funds,
    "get_holdings": _get_holdings,
    "get_current_rules": _get_current_rules,
    "search_documents": _search_documents,
}
