from __future__ import annotations
from .tool_result import ToolResult
from .db import execute_query
from .schema_adapter import get_table

_SPLIT_COLS = ["scheme_id", "scheme_name", "large_cap_pct", "mid_cap_pct", "small_cap_pct"]


def _resolve_scheme_id(identifier: str) -> str | None:
    t = get_table("scheme_master")
    rows = execute_query(
        f"SELECT scheme_id FROM {t} "
        f"WHERE scheme_id = :v OR amfi_code = :v OR isin = :v OR scheme_name ILIKE :vlike LIMIT 1",
        {"v": identifier, "vlike": f"%{identifier}%"},
    )
    return rows[0]["scheme_id"] if rows else None


def get_market_cap_split(scheme_identifier: str) -> ToolResult:
    sid = _resolve_scheme_id(scheme_identifier)
    if not sid:
        return ToolResult(f"Scheme '{scheme_identifier}' not found.", [], _SPLIT_COLS)
    sm = get_table("scheme_master")
    mc = get_table("market_cap_allocation")
    rows = execute_query(
        f"SELECT s.scheme_id, s.scheme_name, m.large_cap_pct, m.mid_cap_pct, m.small_cap_pct "
        f"FROM {sm} s JOIN {mc} m ON s.scheme_id = m.scheme_id WHERE s.scheme_id = :sid",
        {"sid": sid},
    )
    return ToolResult(
        narrative_summary=f"Market cap split for scheme {sid}.",
        table=rows, columns=_SPLIT_COLS,
        citations=[f"altstreet_market_cap_allocation | scheme_id={sid}"],
    )


def filter_by_cap_exposure(
    category: str = "",
    large_cap_min: float = -1, large_cap_max: float = -1,
    mid_cap_min: float = -1, mid_cap_max: float = -1,
    small_cap_min: float = -1, small_cap_max: float = -1,
) -> ToolResult:
    sm = get_table("scheme_master")
    mc = get_table("market_cap_allocation")
    clauses = ["s.scheme_id = m.scheme_id"]
    params: dict = {}
    if category:
        clauses.append("(s.category ILIKE :cat OR COALESCE(s.sub_category,'') ILIKE :cat)")
        params["cat"] = f"%{category}%"
    thresholds = [
        ("large_cap_min", "m.large_cap_pct >= :large_cap_min", large_cap_min),
        ("large_cap_max", "m.large_cap_pct <= :large_cap_max", large_cap_max),
        ("mid_cap_min",   "m.mid_cap_pct >= :mid_cap_min",     mid_cap_min),
        ("mid_cap_max",   "m.mid_cap_pct <= :mid_cap_max",     mid_cap_max),
        ("small_cap_min", "m.small_cap_pct >= :small_cap_min", small_cap_min),
        ("small_cap_max", "m.small_cap_pct <= :small_cap_max", small_cap_max),
    ]
    for key, clause, val in thresholds:
        if val >= 0:
            clauses.append(clause)
            params[key] = val
    where = " AND ".join(clauses)
    rows = execute_query(
        f"SELECT s.scheme_id, s.scheme_name, m.large_cap_pct, m.mid_cap_pct, m.small_cap_pct "
        f"FROM {sm} s, {mc} m WHERE {where} ORDER BY s.scheme_name",
        params,
    )
    return ToolResult(
        narrative_summary=f"Found {len(rows)} schemes matching cap exposure filters.",
        table=rows, columns=_SPLIT_COLS,
        citations=["altstreet_scheme_master + altstreet_market_cap_allocation | cap exposure filter"],
    )


def count_breaches(
    rule_type: str = "large_cap_small_cap_breach",
    small_cap_max: float = 10.0,
) -> ToolResult:
    sm = get_table("scheme_master")
    mc = get_table("market_cap_allocation")
    rows = execute_query(
        f"SELECT s.scheme_id, s.scheme_name, m.large_cap_pct, m.small_cap_pct "
        f"FROM {sm} s JOIN {mc} m ON s.scheme_id = m.scheme_id "
        f"WHERE s.category ILIKE '%Large Cap%' "
        f"  AND m.large_cap_pct >= 65 AND m.small_cap_pct > :sc_max "
        f"ORDER BY m.small_cap_pct DESC",
        {"sc_max": small_cap_max},
    )
    return ToolResult(
        narrative_summary=f"Found {len(rows)} large-cap funds with small_cap_pct > {small_cap_max}%.",
        table=rows, columns=["scheme_id", "scheme_name", "large_cap_pct", "small_cap_pct"],
        citations=["altstreet_market_cap_allocation | large cap breach rule"],
    )
