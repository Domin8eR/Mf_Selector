"""Allow-listed tool registry for the AltStreet AI layer.

Every function reads from internal validated tables — selfmade_* (app-curated,
used by the ranking/metrics/holdings tools that predate this module's scope)
or the altstreet_* normalizing views over ingested vendor data (used by the
general scheme/exposure/company-holdings browse tools, consistent with how
routers/rankings.py and routers/data_quality.py already read them). No vendor
API is called at request time either way.
Every invocation is logged to tool_call_log.

AI does NOT compute metrics — it only retrieves pre-computed results.

2026-07-17: merged in the tools that used to live only in app/research_chat
(scheme_tools, holdings_tools, overlap_tools, exposure_tools, company_tools),
which was a second, disconnected agent with its own unguarded chat surface.
That surface is decommissioned; its genuinely-new capabilities were folded in
here as filter_schemes / get_cap_exposure / get_company_exposure /
compare_holdings_overlap, and its holdings-lookup capability was merged into
the existing get_holdings rather than kept as separate near-duplicate tools.
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
    # Merged from app/research_chat (2026-07-17) — see module docstring below.
    "filter_schemes",
    "get_cap_exposure",
    "get_company_exposure",
    "compare_holdings_overlap",
}

# ── AMC code resolution (ported from research_chat/amc_codes.py) ──────────────
# Vendor amc_code -> display name. Used by filter_schemes() to resolve a
# free-text AMC name (e.g. "HDFC") to the numeric codes altstreet_scheme_master
# stores, and to resolve codes back to names in results.

AMC_CODE_TO_NAME: dict[str, str] = {
    "400001": "Baroda BNP Paribas MF", "400004": "Aditya Birla Sun Life MF",
    "400006": "Canara Robeco MF", "400009": "DSP MF", "400010": "Quant MF",
    "400012": "Franklin Templeton MF", "400013": "HDFC MF", "400014": "HSBC MF",
    "400015": "ICICI Prudential MF", "400019": "Kotak MF", "400020": "LIC MF",
    "400021": "Invesco India MF", "400024": "Quantum MF", "400025": "Nippon India MF",
    "400027": "SBI MF", "400028": "Bandhan MF", "400029": "Sundaram MF",
    "400030": "Tata MF", "400032": "UTI MF", "400033": "Mirae Asset MF",
    "400040": "Axis MF", "400041": "Navi MF", "400042": "Motilal Oswal MF",
    "400044": "PGIM India MF", "400045": "Union MF", "400047": "360 ONE MF",
    "400049": "Parag Parikh MF", "400054": "Mahindra Manulife MF",
    "400055": "WhiteOak Capital MF", "400057": "Trust MF", "400058": "NJ MF",
    "400059": "Samco MF", "400060": "Bajaj Finserv MF", "400062": "Zerodha MF",
    "400066": "JioBlackRock MF",
}


def _resolve_amc_name(code: str) -> str:
    return AMC_CODE_TO_NAME.get(str(code), code)


def _resolve_amc_codes(query: str) -> list[str]:
    q = query.lower()
    return [code for code, name in AMC_CODE_TO_NAME.items() if q in name.lower()]


def _resolve_schemecode(identifier: str, db: Session) -> tuple[int, str, str | None] | tuple[None, None, None]:
    """Resolve a free-text fund identifier (code, AMFI code, ISIN, or name substring)
    to (schemecode, scheme_name, resolution_note) via altstreet_scheme_master.
    Returns (None, None, None) if nothing matches at all. Used by tools reachable
    through free-text chat, where the user names a fund instead of passing its
    numeric schemecode directly.

    A name substring routinely matches several real rows for the same underlying
    fund — Direct/Regular plan x Growth/IDCW option x payout variants (e.g. "PGIM
    India Large Cap" matches 8 real schemes). Previously this picked whichever row
    Postgres returned first (LIMIT 1, no ORDER BY) — arbitrary and silent. Now:
      1. Prefer Direct plan over Regular (accord_fintech_scheme_details.plan — the
         same lookup Category Rankings' Direct/Regular pill uses, _PLAN_LABELS in
         app.routers.rankings — not reimplemented here).
      2. Among those, prefer a Growth option over IDCW/Dividend/Payout (scheme_name
         text — there is no vetted opt_code mapping elsewhere in the codebase to
         reuse for this half).
    resolution_note is None when the match was unambiguous (a single real row, or
    an exact scheme_id/amfi_code/isin match). It is set whenever more than one
    real fund matched — including when the preference order above still leaves a
    tie — so a caller's final answer can disclose that a choice was made instead
    of presenting the picked schemecode as the only real answer.
    """
    from sqlalchemy import text
    from app.routers.rankings import _PLAN_LABELS

    # Exact key match (scheme_id / amfi_code / isin) identifies one specific row
    # by construction — no ambiguity possible.
    exact = db.execute(
        text(
            "SELECT scheme_id, scheme_name FROM altstreet_scheme_master "
            "WHERE scheme_id = :v OR amfi_code = :v OR isin = :v LIMIT 1"
        ),
        {"v": identifier},
    ).fetchone()
    if exact:
        return int(exact[0]), exact[1], None

    rows = db.execute(
        text(
            "SELECT asm.scheme_id, asm.scheme_name, sd.plan "
            "FROM altstreet_scheme_master asm "
            "LEFT JOIN accord_fintech_scheme_details sd ON sd.schemecode = asm.scheme_id::integer "
            "WHERE asm.scheme_name ILIKE :vlike "
            "ORDER BY asm.scheme_id"
        ),
        {"vlike": f"%{identifier}%"},
    ).fetchall()

    if not rows:
        return None, None, None
    if len(rows) == 1:
        return int(rows[0][0]), rows[0][1], None

    def _is_direct(r: Any) -> bool:
        return _PLAN_LABELS.get(r[2]) == "Direct"

    def _is_growth(r: Any) -> bool:
        n = r[1].lower()
        return "growth" in n and "idcw" not in n and "dividend" not in n

    direct_growth = [r for r in rows if _is_direct(r) and _is_growth(r)]
    direct_any = [r for r in rows if _is_direct(r)]
    growth_any = [r for r in rows if _is_growth(r)]
    candidates = direct_growth or direct_any or growth_any or rows

    picked = candidates[0]
    schemecode, name = int(picked[0]), picked[1]
    other_names = [r[1] for r in rows if int(r[0]) != schemecode]

    if len(candidates) == 1:
        note = (
            f"'{identifier}' matched {len(rows)} real funds (Direct/Regular, "
            f"Growth/IDCW variants); picked '{name}' (Direct plan + Growth option "
            f"preferred). {len(other_names)} other real match(es) also exist, "
            f"e.g. {other_names[0]!r}."
        )
    else:
        # Direct+Growth preference didn't narrow it to one row (e.g. genuinely
        # duplicate Direct+Growth entries) — the pick among the tied candidates
        # is arbitrary (lowest scheme_id), and that must stay visible too.
        tied_names = [r[1] for r in candidates if int(r[0]) != schemecode]
        note = (
            f"'{identifier}' matched {len(rows)} real funds, and {len(candidates)} "
            f"remained tied even after preferring Direct plan + Growth option. "
            f"Picked '{name}' (schemecode {schemecode}) arbitrarily among the tie — "
            f"other tied match(es): {tied_names}."
        )

    return schemecode, name, note


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
    """Compare multiple funds side-by-side on metrics and returns.

    Resolves each fund via schemecodes (already-numeric, e.g. from page
    context) or scheme_identifiers / scheme_identifier_a+scheme_identifier_b
    (free-text names — the shape the intent-classifier LLM actually produces
    for a 2-fund "compare X and Y" query, mirroring compare_holdings_overlap's
    resolution pattern below), then calls build_fund_comparison() — the same
    canonical implementation POST /compare/funds uses, so a fund outside the
    governed ranked universe degrades honestly here too instead of this tool
    silently requiring numeric codes it was never given.
    """
    from app.services.compare_service import build_fund_comparison

    schemecodes: list[int] = []
    unresolved: list[str] = []
    resolution_notes: list[str] = []

    for sc in params.get("schemecodes", []):
        schemecodes.append(int(sc))

    identifiers: list[str] = list(params.get("scheme_identifiers", []))
    for key in ("scheme_identifier_a", "scheme_identifier_b"):
        if params.get(key):
            identifiers.append(params[key])

    for identifier in identifiers:
        sc, _name, note = _resolve_schemecode(identifier, db)
        if sc is None:
            unresolved.append(identifier)
        else:
            schemecodes.append(sc)
            if note:
                resolution_notes.append(note)

    if unresolved:
        return {"error": f"Could not resolve fund(s): {', '.join(unresolved)}"}
    if len(schemecodes) < 2:
        return {"error": "compare_funds requires at least 2 funds (schemecodes or scheme_identifiers)"}

    try:
        result = build_fund_comparison(db, schemecodes)
    except ValueError as exc:
        return {"error": str(exc)}

    # Trim to what a chat answer needs. build_fund_comparison() also returns
    # holdings_overlap (pairs/common_holdings/sector_table), radar_data, and
    # rank_history for the Fund Comparison page's charts — none of that is
    # relevant to a text/table chat answer, and including it pushed a single
    # tool result well past generate_response's per-result context budget
    # (_respond_llm truncates each tool result to 3000 chars), silently
    # cutting off the second/third fund's metrics before the LLM ever saw them.
    trimmed: dict = {
        "source_tables": result["source_tables"],
        "funds": [
            {
                "schemecode": f["schemecode"],
                "fund_name": f["fund_name"],
                "amc_name": f["amc_name"],
                "category": f["category"],
                "rank": f["rank"],
                "composite_score": f["composite_score"],
                "status_label": f["status_label"],
                "coverage_note": f["coverage_note"],
                "as_of_date": f["as_of_date"],
                "metrics": f["metrics"],
                "active_share": f["active_share"].get("value"),
                "portfolio_stability": f["portfolio_stability"].get("value"),
                "expense_ratio_pct": f["expense_ratio_pct"].get("value"),
                "aum_cr": f["aum_cr"],
            }
            for f in result["funds"]
        ],
    }
    # Which real fund a free-text name resolved to, when more than one real
    # fund matched it — must stay visible in the final answer, not just in
    # the tool_call_log, so the resolved variant is never presented as if it
    # were the only real match.
    if resolution_notes:
        trimmed["fund_resolution_notes"] = resolution_notes
    return trimmed


def _get_holdings(params: dict, db: Session) -> dict:
    """Return portfolio holdings for a fund.

    Accepts either schemecode (int, original param) or scheme_identifier
    (free-text name/AMFI code/ISIN — resolved via altstreet_scheme_master,
    for callers coming from free-text chat rather than a page that already
    knows the schemecode). Optional top_n, sort_by ("weight"|"market_cap"),
    cap_type ("Large Cap"|"Mid Cap"|"Small Cap") filter, and
    include_concentration (adds top_1_pct/top_5_pct/herfindahl_index) —
    absorbs what were separately count_holdings/list_holdings/
    concentration_metrics/list_holdings_by_market_cap in research_chat.
    """
    from sqlalchemy import text

    schemecode = int(params["schemecode"]) if params.get("schemecode") else None
    fund_name_hint = None
    resolution_note = None
    if schemecode is None and params.get("scheme_identifier"):
        schemecode, fund_name_hint, resolution_note = _resolve_schemecode(params["scheme_identifier"], db)
        if schemecode is None:
            return {"error": f"No scheme found matching '{params['scheme_identifier']}'"}
    if schemecode is None:
        return {"error": "get_holdings requires schemecode or scheme_identifier"}

    top_n = min(int(params.get("top_n", 10)), 30) if not params.get("include_concentration") else None
    sort_col = "ph.holding_weight_pct" if params.get("sort_by", "weight") != "market_cap" else "sm.market_cap_bucket"
    cap_type = params.get("cap_type")

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

    sql = (
        "SELECT sm.company_name, sm.sector, sm.market_cap_bucket, "
        "       ph.holding_weight_pct "
        "FROM selfmade_portfolio_holding ph "
        "JOIN selfmade_security_master sm ON sm.id = ph.security_id "
        "WHERE ph.scheme_id = :sc AND ph.as_of_date = :d "
    )
    q_params: dict = {"sc": schemecode, "d": as_of_date}
    if cap_type:
        sql += "AND sm.market_cap_bucket = :cap "
        q_params["cap"] = cap_type
    sql += f"ORDER BY {sort_col} DESC "
    if top_n:
        sql += "LIMIT :n"
        q_params["n"] = top_n

    rows = db.execute(text(sql), q_params).fetchall()

    name_row = db.execute(
        text(
            "SELECT fund_name FROM selfmade_ranking_snapshot "
            "WHERE schemecode = :sc ORDER BY snapshot_date DESC LIMIT 1"
        ),
        {"sc": schemecode},
    ).fetchone()

    result: dict = {
        "schemecode": schemecode,
        "fund_name": (name_row[0] if name_row else None) or fund_name_hint or str(schemecode),
        "as_of_date": str(as_of_date),
        "source_tables": ["selfmade_portfolio_holding", "selfmade_security_master"],
        "holding_count": len(rows),
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

    if params.get("include_concentration"):
        weights = sorted((float(r[3]) for r in rows), reverse=True)
        result["concentration"] = {
            "top_1_pct": round(weights[0], 4) if weights else 0.0,
            "top_5_pct": round(sum(weights[:5]), 4),
            "herfindahl_index": round(sum(w ** 2 for w in weights), 4),
        }

    if resolution_note:
        result["fund_resolution_note"] = resolution_note

    return result


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

    from app.quant.metrics import cagr_from_total_return

    fund_1y = round(float(sr[0]), 2) if sr and sr[0] is not None else None
    fund_3y = round(float(sr[1]), 2) if sr and sr[1] is not None else None
    fund_5y = round(float(sr[2]), 2) if sr and sr[2] is not None else None
    bm_1y = cagr_from_total_return(float(sr[3]) if sr and sr[3] is not None else None, 1.0)
    bm_3y = cagr_from_total_return(float(sr[4]) if sr and sr[4] is not None else None, 3.0)
    bm_5y = cagr_from_total_return(float(sr[5]) if sr and sr[5] is not None else None, 5.0)

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


def _filter_schemes(params: dict, db: Session) -> dict:
    """General scheme universe browse: filter / count / group-by-AMC / sort.

    Consolidates research_chat's list_schemes + count_schemes + group_by_amc +
    sort_schemes into one tool — those were query-shape variants of the same
    underlying browse, not distinct capabilities, so registering all four
    separately would just give the classifier an ambiguous choice.

    filters keys: amc, category, sub_category, status (default "Active"),
    aum_min, aum_max (crores), launch_date_before, launch_date_after (ISO dates).
    mode: group_by="amc" returns per-AMC counts; count_only=true returns just
    the total; otherwise returns the matching rows (sorted by sort_by/sort_dir,
    capped at limit).
    """
    from sqlalchemy import text

    filters = params.get("filters") or {}
    t = "altstreet_scheme_master"
    clauses: list[str] = []
    q_params: dict = {}

    if filters.get("amc"):
        amc_raw = filters["amc"]
        codes = _resolve_amc_codes(amc_raw)
        if codes:
            placeholders = ", ".join(f":amc_code{i}" for i in range(len(codes)))
            clauses.append(f"(amc IN ({placeholders}) OR scheme_name ILIKE :amc_name)")
            q_params["amc_name"] = f"%{amc_raw}%"
            for i, code in enumerate(codes):
                q_params[f"amc_code{i}"] = code
        else:
            clauses.append("(amc ILIKE :amc OR scheme_name ILIKE :amc)")
            q_params["amc"] = f"%{amc_raw}%"

    if filters.get("category"):
        clauses.append("(category ILIKE :cat OR COALESCE(sub_category,'') ILIKE :cat)")
        q_params["cat"] = f"%{filters['category']}%"

    if filters.get("sub_category"):
        clauses.append("sub_category ILIKE :sub_cat")
        q_params["sub_cat"] = f"%{filters['sub_category']}%"

    if filters.get("status"):
        clauses.append("status ILIKE :status")
        q_params["status"] = filters["status"]
    elif not filters.get("amc"):
        clauses.append("status = :status")
        q_params["status"] = "Active"

    if filters.get("aum_min") is not None:
        clauses.append("aum >= :aum_min")
        q_params["aum_min"] = float(filters["aum_min"])
    if filters.get("aum_max") is not None:
        clauses.append("aum <= :aum_max")
        q_params["aum_max"] = float(filters["aum_max"])
    if filters.get("launch_date_before"):
        clauses.append("launch_date < :launch_before")
        q_params["launch_before"] = filters["launch_date_before"]
    if filters.get("launch_date_after"):
        clauses.append("launch_date > :launch_after")
        q_params["launch_after"] = filters["launch_date_after"]

    where = " AND ".join(clauses) if clauses else "1=1"

    if filters.get("count_only") or params.get("count_only"):
        total = db.execute(text(f"SELECT COUNT(*) FROM {t} WHERE {where}"), q_params).scalar() or 0
        return {
            "source_table": t,
            "filters": filters,
            "count": int(total),
        }

    if params.get("group_by") == "amc":
        rows = db.execute(text(f"SELECT amc FROM {t} WHERE {where}"), q_params).fetchall()
        groups: dict[str, int] = {}
        for r in rows:
            name = _resolve_amc_name(r[0])
            groups[name] = groups.get(name, 0) + 1
        return {
            "source_table": t,
            "filters": filters,
            "amc_count": len(groups),
            "groups": [{"amc": k, "scheme_count": v} for k, v in sorted(groups.items())],
        }

    sort_by = params.get("sort_by", "scheme_name")
    sort_dir = "DESC" if params.get("sort_dir", "asc").lower() == "desc" else "ASC"
    limit = min(int(params.get("limit", 50)), 100)
    rows = db.execute(
        text(f"SELECT scheme_id, scheme_name, amc, category, sub_category, aum, "
             f"launch_date, status FROM {t} WHERE {where} ORDER BY {sort_by} {sort_dir} LIMIT :lim"),
        {**q_params, "lim": limit},
    ).fetchall()

    return {
        "source_table": t,
        "filters": filters,
        "result_count": len(rows),
        "schemes": [
            {
                "scheme_id": r[0],
                "scheme_name": r[1],
                "amc": _resolve_amc_name(r[2]) if r[2] else None,
                "category": r[3],
                "sub_category": r[4],
                "aum_crores": float(r[5]) if r[5] is not None else None,
                "launch_date": str(r[6]) if r[6] else None,
                "status": r[7],
            }
            for r in rows
        ],
    }


def _get_cap_exposure(params: dict, db: Session) -> dict:
    """Market-cap composition: single-fund split, or multi-fund threshold screen.

    Consolidates get_market_cap_split + filter_by_cap_exposure + count_breaches
    (a hardcoded large_cap_min=65 preset of the same filter) into one tool.
    Pass schemecode/scheme_identifier for a single fund's split; pass any of
    large_cap_min/max, mid_cap_min/max, small_cap_min/max (+ optional category)
    for a filtered list across funds.
    """
    from sqlalchemy import text

    sm, mc = "altstreet_scheme_master", "altstreet_market_cap_allocation"

    identifier = params.get("scheme_identifier")
    schemecode = int(params["schemecode"]) if params.get("schemecode") else None
    resolution_note = None
    if schemecode is None and identifier:
        schemecode, _name, resolution_note = _resolve_schemecode(identifier, db)
        if schemecode is None:
            return {"error": f"No scheme found matching '{identifier}'"}

    if schemecode is not None:
        row = db.execute(
            text(f"SELECT s.scheme_id, s.scheme_name, m.large_cap_pct, m.mid_cap_pct, m.small_cap_pct "
                 f"FROM {sm} s JOIN {mc} m ON s.scheme_id = m.scheme_id WHERE s.scheme_id = :sid"),
            {"sid": str(schemecode)},
        ).fetchone()
        if not row:
            return {"error": f"No cap exposure data for schemecode {schemecode}"}
        result = {
            "source_tables": [sm, mc],
            "scheme_id": row[0],
            "fund_name": row[1],
            "large_cap_pct": float(row[2]) if row[2] is not None else None,
            "mid_cap_pct": float(row[3]) if row[3] is not None else None,
            "small_cap_pct": float(row[4]) if row[4] is not None else None,
        }
        if resolution_note:
            result["fund_resolution_note"] = resolution_note
        return result

    clauses = ["s.scheme_id = m.scheme_id"]
    q_params: dict = {}
    if params.get("category"):
        clauses.append("(s.category ILIKE :cat OR COALESCE(s.sub_category,'') ILIKE :cat)")
        q_params["cat"] = f"%{params['category']}%"
    thresholds = [
        ("large_cap_min", "m.large_cap_pct >= :large_cap_min"),
        ("large_cap_max", "m.large_cap_pct <= :large_cap_max"),
        ("mid_cap_min",   "m.mid_cap_pct >= :mid_cap_min"),
        ("mid_cap_max",   "m.mid_cap_pct <= :mid_cap_max"),
        ("small_cap_min", "m.small_cap_pct >= :small_cap_min"),
        ("small_cap_max", "m.small_cap_pct <= :small_cap_max"),
    ]
    for key, clause in thresholds:
        if params.get(key) is not None:
            clauses.append(clause)
            q_params[key] = float(params[key])

    if len(clauses) == 1:
        return {"error": "get_cap_exposure requires either a scheme identifier or at least one threshold"}

    where = " AND ".join(clauses)
    rows = db.execute(
        text(f"SELECT s.scheme_id, s.scheme_name, m.large_cap_pct, m.mid_cap_pct, m.small_cap_pct "
             f"FROM {sm} s, {mc} m WHERE {where} ORDER BY s.scheme_name LIMIT 50"),
        q_params,
    ).fetchall()

    return {
        "source_tables": [sm, mc],
        "filters": {k: v for k, v in params.items() if k != "filters"},
        "result_count": len(rows),
        "schemes": [
            {
                "scheme_id": r[0], "fund_name": r[1],
                "large_cap_pct": float(r[2]) if r[2] is not None else None,
                "mid_cap_pct": float(r[3]) if r[3] is not None else None,
                "small_cap_pct": float(r[4]) if r[4] is not None else None,
            }
            for r in rows
        ],
    }


def _get_company_exposure(params: dict, db: Session) -> dict:
    """All schemes holding a given company, with weight and market value.

    Consolidates count_schemes_holding_company + aggregate_company_exposure —
    the count was always just len() of the aggregate list, not a separate
    capability. Reads altstreet_scheme_holdings (over accord_fintech_mf_
    portfolio) rather than the curated selfmade_security_master, because the
    curated set only covers ~75 seeded securities across the 3 equity
    categories — company exposure search needs the full holdings universe.
    """
    from sqlalchemy import text

    company_name = params.get("company_name", "")
    if not company_name:
        return {"error": "company_name parameter is required"}
    min_weight_pct = float(params.get("min_weight_pct", 0) or 0)

    sh, sm = "altstreet_scheme_holdings", "altstreet_scheme_master"
    rows = db.execute(
        text(f"SELECT h.scheme_id, s.scheme_name, h.weight, h.market_value "
             f"FROM {sh} h JOIN {sm} s ON h.scheme_id = s.scheme_id "
             f"WHERE h.company_name ILIKE :q ORDER BY h.weight DESC"),
        {"q": f"%{company_name}%"},
    ).fetchall()

    schemes = []
    for r in rows:
        weight_pct = float(r[2]) if r[2] is not None else None
        if min_weight_pct and (weight_pct or 0) < min_weight_pct:
            continue
        schemes.append({
            "scheme_id": r[0], "fund_name": r[1],
            "weight_pct": weight_pct,
            "market_value_raw": float(r[3]) if r[3] is not None else None,
        })

    return {
        "source_tables": [sh, sm],
        "company_name": company_name,
        "scheme_count": len(schemes),
        "schemes": schemes,
        "data_note": (
            "weight_pct is the holding's % of portfolio (reliable). "
            "market_value_raw is accord_fintech_mf_portfolio.mktval as stored — "
            "its unit is not verified as INR crores (values don't fit that "
            "assumption), so filter/sort by min_weight_pct, not market value."
        ),
    }


def _weights_for_scheme(sc: int, db: Session) -> dict[str, float]:
    """{company_name: weight_pct} for a scheme's latest real holdings snapshot.
    The one canonical holdings-overlap computation both compare_holdings_overlap
    modes below build on — pairwise (two named funds) and one-to-many (find
    funds similar to one named fund) must never define "overlap" differently."""
    from sqlalchemy import text

    date_row = db.execute(
        text("SELECT MAX(as_of_date) FROM selfmade_portfolio_holding WHERE scheme_id = :sc"),
        {"sc": sc},
    ).fetchone()
    if not date_row or not date_row[0]:
        return {}
    rows = db.execute(
        text("SELECT sm.company_name, ph.holding_weight_pct FROM selfmade_portfolio_holding ph "
             "JOIN selfmade_security_master sm ON sm.id = ph.security_id "
             "WHERE ph.scheme_id = :sc AND ph.as_of_date = :d"),
        {"sc": sc, "d": date_row[0]},
    ).fetchall()
    return {r[0]: float(r[1] or 0) for r in rows}


def _similar_funds_by_holdings(sc_a: int, map_a: dict[str, float], db: Session, limit: int) -> list[dict]:
    """Rank every other fund with real holdings data by overlap against fund
    A — same overlap definition as the two-fund path above (sum of min(weight_a,
    weight_b) for common holdings; count-based % too), computed set-based in one
    query instead of a per-fund Python loop calling _weights_for_scheme() (473
    funds currently carry real holdings data — an N+1 loop would be ~1000
    queries for a single chat request)."""
    from sqlalchemy import text

    if not map_a:
        return []

    companies = list(map_a.keys())
    weights = [map_a[c] for c in companies]

    rows = db.execute(
        text("""
            WITH target AS (
                SELECT unnest(CAST(:companies AS text[])) AS company_name,
                       unnest(CAST(:weights AS float[])) AS w
            ),
            latest_dates AS (
                SELECT scheme_id, MAX(as_of_date) AS d
                FROM selfmade_portfolio_holding
                WHERE scheme_id != :sc_a
                GROUP BY scheme_id
            ),
            other_holdings AS (
                SELECT ph.scheme_id, sm.company_name, ph.holding_weight_pct AS w
                FROM selfmade_portfolio_holding ph
                JOIN latest_dates ld ON ld.scheme_id = ph.scheme_id AND ld.d = ph.as_of_date
                JOIN selfmade_security_master sm ON sm.id = ph.security_id
            ),
            per_scheme_counts AS (
                SELECT scheme_id, COUNT(*) AS n FROM other_holdings GROUP BY scheme_id
            ),
            matched AS (
                SELECT oh.scheme_id,
                       COUNT(*) AS common_count,
                       SUM(LEAST(oh.w, t.w)) AS overlap_weight
                FROM other_holdings oh
                JOIN target t ON t.company_name = oh.company_name
                GROUP BY oh.scheme_id
            )
            SELECT
                m.scheme_id,
                COALESCE(asm.scheme_name, 'Fund ' || m.scheme_id::text) AS fund_name,
                m.common_count,
                m.overlap_weight,
                GREATEST(psc.n, :target_count) AS denom
            FROM matched m
            JOIN per_scheme_counts psc ON psc.scheme_id = m.scheme_id
            LEFT JOIN altstreet_scheme_master asm ON asm.scheme_id::integer = m.scheme_id
            ORDER BY m.overlap_weight DESC
            LIMIT :lim
        """),
        {
            "companies": companies,
            "weights": weights,
            "sc_a": sc_a,
            "target_count": len(companies),
            "lim": limit,
        },
    ).fetchall()

    return [
        {
            "schemecode": int(r[0]),
            "fund_name": r[1],
            "common_holdings_count": int(r[2]),
            "overlap_by_weight_pct": round(float(r[3]), 4),
            "overlap_by_count_pct": round(int(r[2]) / max(int(r[4]), 1) * 100, 2),
        }
        for r in rows
    ]


def _compare_holdings_overlap(params: dict, db: Session) -> dict:
    """Portfolio overlap — two modes on the same underlying computation.

    Two funds identified (schemecode_a/b or scheme_identifier_a/b): aggregate
    metrics + per-company weight_a/weight_b breakdown. Consolidates the old
    calculate_overlap + compare_schemes_holdings (same computation, different
    aggregation) into one tool rather than two near-duplicates.

    Only ONE fund identified: "which funds hold similar holdings to X" — a
    real capability that never actually existed (confirmed absent in the
    pre-merge research_chat module too, not just dropped during the merge).
    Ranks every other fund with real holdings data by the same overlap
    definition (_similar_funds_by_holdings), instead of erroring with
    "requires both funds" the way this tool did before.

    Reads selfmade_portfolio_holding, same source as get_holdings, so a fund's
    overlap numbers are always consistent with its individual holdings list.
    """
    from sqlalchemy import text

    def _resolve(key_code: str, key_id: str) -> tuple[int, str, str | None] | tuple[None, None, None]:
        if params.get(key_code):
            sc = int(params[key_code])
            row = db.execute(
                text("SELECT fund_name FROM selfmade_ranking_snapshot WHERE schemecode = :sc "
                     "ORDER BY snapshot_date DESC LIMIT 1"),
                {"sc": sc},
            ).fetchone()
            return sc, (row[0] if row else str(sc)), None
        if params.get(key_id):
            return _resolve_schemecode(params[key_id], db)
        return None, None, None

    sc_a, name_a, note_a = _resolve("schemecode_a", "scheme_identifier_a")
    sc_b, name_b, note_b = _resolve("schemecode_b", "scheme_identifier_b")

    if sc_a is None and sc_b is None:
        return {"error": "compare_holdings_overlap requires at least one fund identified "
                          "(schemecode_a/b or scheme_identifier_a/b)"}

    # One fund only — "find similar funds" mode.
    if sc_a is None or sc_b is None:
        sc, name, note = (sc_a, name_a, note_a) if sc_a is not None else (sc_b, name_b, note_b)
        map_ref = _weights_for_scheme(sc, db)
        if not map_ref:
            return {"error": f"No holdings found for schemecode {sc}"}

        limit = min(int(params.get("limit", 10)), 25)
        similar = _similar_funds_by_holdings(sc, map_ref, db, limit)

        result: dict = {
            "source_tables": ["selfmade_portfolio_holding", "selfmade_security_master"],
            "mode": "similar_funds",
            "reference_fund": {"schemecode": sc, "fund_name": name},
            "similar_funds": similar,
        }
        if not similar:
            result["data_note"] = (
                f"'{name}' has real holdings data but no other fund with holdings "
                "data shares any common holding with it."
            )
        if note:
            result["fund_resolution_notes"] = [note]
        return result

    map_a, map_b = _weights_for_scheme(sc_a, db), _weights_for_scheme(sc_b, db)
    if not map_a or not map_b:
        return {"error": f"No holdings found for schemecode {sc_a if not map_a else sc_b}"}

    common = sorted(set(map_a) & set(map_b))
    overlap_weight_pct = round(sum(min(map_a[n], map_b[n]) for n in common), 4)
    overlap_count_pct = round(len(common) / max(len(map_a), len(map_b), 1) * 100, 2)

    result: dict = {
        "source_tables": ["selfmade_portfolio_holding", "selfmade_security_master"],
        "fund_a": {"schemecode": sc_a, "fund_name": name_a},
        "fund_b": {"schemecode": sc_b, "fund_name": name_b},
        "common_holdings_count": len(common),
        "overlap_by_count_pct": overlap_count_pct,
        "overlap_by_weight_pct": overlap_weight_pct,
        "common_holdings": [
            {"company": n, "weight_a": round(map_a[n], 4), "weight_b": round(map_b[n], 4)}
            for n in sorted(common, key=lambda n: map_a[n], reverse=True)
        ],
    }
    notes = [n for n in (note_a, note_b) if n]
    if notes:
        result["fund_resolution_notes"] = notes
    return result


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
    "filter_schemes": _filter_schemes,
    "get_cap_exposure": _get_cap_exposure,
    "get_company_exposure": _get_company_exposure,
    "compare_holdings_overlap": _compare_holdings_overlap,
}
