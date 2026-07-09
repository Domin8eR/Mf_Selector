from __future__ import annotations
from .tool_result import ToolResult
from .db import execute_query
from .schema_adapter import get_table


def count_schemes_holding_company(company_name: str) -> ToolResult:
    t = get_table("scheme_holdings")
    rows = execute_query(
        f"SELECT COUNT(DISTINCT scheme_id) AS cnt FROM {t} WHERE company_name ILIKE :q",
        {"q": f"%{company_name}%"},
    )
    total = rows[0]["cnt"] if rows else 0
    return ToolResult(
        narrative_summary=f"{total} schemes hold '{company_name}'.",
        table=[{"company_name": company_name, "scheme_count": total}],
        columns=["company_name", "scheme_count"],
        citations=["altstreet_scheme_holdings | count by company"],
    )


def aggregate_company_exposure(
    company_name: str,
    min_market_value_crores: float = 0,
) -> ToolResult:
    sh = get_table("scheme_holdings")
    sm = get_table("scheme_master")
    rows = execute_query(
        f"SELECT h.scheme_id, s.scheme_name, h.weight, h.market_value "
        f"FROM {sh} h JOIN {sm} s ON h.scheme_id = s.scheme_id "
        f"WHERE h.company_name ILIKE :q ORDER BY h.weight DESC",
        {"q": f"%{company_name}%"},
    )
    for r in rows:
        r["market_value_crores"] = round((r.get("market_value") or 0) / 1e7, 2)
    if min_market_value_crores > 0:
        rows = [r for r in rows if r["market_value_crores"] >= min_market_value_crores]
    return ToolResult(
        narrative_summary=f"Found {len(rows)} schemes holding '{company_name}'" +
            (f" with >= {min_market_value_crores} Cr." if min_market_value_crores else "."),
        table=rows,
        columns=["scheme_id", "scheme_name", "weight", "market_value", "market_value_crores"],
        citations=["altstreet_scheme_holdings | company exposure"],
    )
