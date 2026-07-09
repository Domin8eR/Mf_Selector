from __future__ import annotations
from .tool_result import ToolResult
from .db import execute_query
from .schema_adapter import get_table

_HOLDING_COLS = ["company_name", "weight", "quantity", "market_value", "market_value_crores"]


def _resolve_scheme_id(identifier: str) -> tuple[str, str] | tuple[None, None]:
    t = get_table("scheme_master")
    rows = execute_query(
        f"SELECT scheme_id, scheme_name FROM {t} "
        f"WHERE scheme_id = :v OR amfi_code = :v OR isin = :v OR scheme_name ILIKE :vlike LIMIT 1",
        {"v": identifier, "vlike": f"%{identifier}%"},
    )
    if rows:
        return rows[0]["scheme_id"], rows[0]["scheme_name"]
    return None, None


def count_holdings(scheme_identifier: str) -> ToolResult:
    sid, sname = _resolve_scheme_id(scheme_identifier)
    if not sid:
        return ToolResult(f"Scheme '{scheme_identifier}' not found.", [], ["scheme_name", "holding_count"])
    t = get_table("scheme_holdings")
    rows = execute_query(f"SELECT COUNT(*) AS cnt FROM {t} WHERE scheme_id = :sid", {"sid": sid})
    total = rows[0]["cnt"] if rows else 0
    return ToolResult(
        narrative_summary=f"Scheme '{sname}' has {total} holdings.",
        table=[{"scheme_name": sname, "holding_count": total}],
        columns=["scheme_name", "holding_count"],
        citations=[f"altstreet_scheme_holdings | scheme_id={sid}"],
    )


def list_holdings(
    scheme_identifier: str,
    top_n: int | None = None,
    sort_by: str = "weight",
) -> ToolResult:
    sid, sname = _resolve_scheme_id(scheme_identifier)
    if not sid:
        return ToolResult(f"Scheme '{scheme_identifier}' not found.", [], _HOLDING_COLS)
    t = get_table("scheme_holdings")
    sql = f"SELECT company_name, weight, quantity, market_value FROM {t} WHERE scheme_id = :sid ORDER BY {sort_by} DESC"
    if top_n:
        sql += f" LIMIT {int(top_n)}"
    rows = execute_query(sql, {"sid": sid})
    for r in rows:
        r["market_value_crores"] = round((r.get("market_value") or 0) / 1e7, 2)
    label = f" (top {top_n})" if top_n else ""
    return ToolResult(
        narrative_summary=f"Holdings for '{sname}'{label}: {len(rows)} companies.",
        table=rows, columns=_HOLDING_COLS,
        citations=[f"altstreet_scheme_holdings | scheme_id={sid}"],
    )


def concentration_metrics(scheme_identifier: str) -> ToolResult:
    sid, sname = _resolve_scheme_id(scheme_identifier)
    if not sid:
        return ToolResult(f"Scheme '{scheme_identifier}' not found.", [], ["metric", "value"])
    t = get_table("scheme_holdings")
    rows = execute_query(
        f"SELECT weight FROM {t} WHERE scheme_id = :sid ORDER BY weight DESC", {"sid": sid}
    )
    weights = [float(r["weight"] or 0) for r in rows]
    top1 = round(weights[0], 4) if weights else 0
    top5 = round(sum(weights[:5]), 4)
    hhi = round(sum(w ** 2 for w in weights), 4)
    metrics = [
        {"metric": "top_1_pct", "value": top1},
        {"metric": "top_5_pct", "value": top5},
        {"metric": "herfindahl_index", "value": hhi},
    ]
    return ToolResult(
        narrative_summary=f"Concentration metrics for '{sname}'.",
        table=metrics, columns=["metric", "value"],
        citations=[f"altstreet_scheme_holdings | scheme_id={sid}"],
    )


def list_holdings_by_market_cap(scheme_identifier: str, cap_type: str = "Large Cap") -> ToolResult:
    sid, sname = _resolve_scheme_id(scheme_identifier)
    if not sid:
        return ToolResult(f"Scheme '{scheme_identifier}' not found.", [], ["company_name", "weight", "market_cap_category"])
    sh = get_table("scheme_holdings")
    cm = get_table("company_master")
    rows = execute_query(
        f"SELECT h.company_name, h.weight, c.market_cap_category "
        f"FROM {sh} h LEFT JOIN {cm} c ON h.company_name ILIKE c.company_name "
        f"WHERE h.scheme_id = :sid AND c.market_cap_category = :cap "
        f"ORDER BY h.weight DESC",
        {"sid": sid, "cap": cap_type},
    )
    return ToolResult(
        narrative_summary=f"'{sname}' has {len(rows)} {cap_type} holdings.",
        table=rows, columns=["company_name", "weight", "market_cap_category"],
        citations=[f"altstreet_scheme_holdings + company_master | scheme_id={sid} cap_type={cap_type}"],
    )


def compare_schemes_holdings(scheme_a: str, scheme_b: str) -> ToolResult:
    sid_a, sname_a = _resolve_scheme_id(scheme_a)
    sid_b, sname_b = _resolve_scheme_id(scheme_b)
    if not sid_a or not sid_b:
        return ToolResult("One or both schemes not found.", [], ["company_name", "weight_a", "weight_b"])
    t = get_table("scheme_holdings")
    rows_a = execute_query(f"SELECT company_name, weight FROM {t} WHERE scheme_id = :sid", {"sid": sid_a})
    rows_b = execute_query(f"SELECT company_name, weight FROM {t} WHERE scheme_id = :sid", {"sid": sid_b})
    map_a = {r["company_name"]: float(r["weight"] or 0) for r in rows_a}
    map_b = {r["company_name"]: float(r["weight"] or 0) for r in rows_b}
    common = [
        {"company_name": name, "weight_a": map_a[name], "weight_b": map_b[name]}
        for name in map_a if name in map_b
    ]
    common.sort(key=lambda x: x["weight_a"], reverse=True)
    return ToolResult(
        narrative_summary=f"'{sname_a}' and '{sname_b}' share {len(common)} companies.",
        table=common, columns=["company_name", "weight_a", "weight_b"],
        citations=[f"altstreet_scheme_holdings | scheme_id={sid_a} vs {sid_b}"],
    )
