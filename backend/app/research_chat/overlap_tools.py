from __future__ import annotations
from .tool_result import ToolResult
from .db import execute_query
from .schema_adapter import get_table


def calculate_overlap(scheme_a: str, scheme_b: str) -> ToolResult:
    t = get_table("scheme_master")
    sh = get_table("scheme_holdings")

    def get_sid(identifier: str) -> str | None:
        rows = execute_query(
            f"SELECT scheme_id FROM {t} WHERE scheme_id=:v OR amfi_code=:v OR isin=:v OR scheme_name ILIKE :vlike LIMIT 1",
            {"v": identifier, "vlike": f"%{identifier}%"},
        )
        return rows[0]["scheme_id"] if rows else None

    sid_a, sid_b = get_sid(scheme_a), get_sid(scheme_b)
    if not sid_a or not sid_b:
        return ToolResult("One or both schemes not found.", [], ["metric", "value"])

    rows_a = execute_query(f"SELECT company_name, weight FROM {sh} WHERE scheme_id=:sid", {"sid": sid_a})
    rows_b = execute_query(f"SELECT company_name, weight FROM {sh} WHERE scheme_id=:sid", {"sid": sid_b})

    map_a = {r["company_name"]: float(r["weight"] or 0) for r in rows_a}
    map_b = {r["company_name"]: float(r["weight"] or 0) for r in rows_b}
    common_names = set(map_a) & set(map_b)

    overlap_weight = round(sum(min(map_a[n], map_b[n]) for n in common_names), 4)
    overlap_count_pct = round(len(common_names) / max(len(map_a), len(map_b), 1) * 100, 2)

    metrics = [
        {"metric": "common_holdings_count", "value": len(common_names)},
        {"metric": "overlap_by_count_pct", "value": overlap_count_pct},
        {"metric": "overlap_by_weight_pct", "value": overlap_weight},
    ]
    return ToolResult(
        narrative_summary=f"Overlap between {scheme_a} and {scheme_b}: {len(common_names)} common holdings, {overlap_weight:.2f}% by weight.",
        table=metrics, columns=["metric", "value"],
        citations=[f"altstreet_scheme_holdings | overlap {sid_a} vs {sid_b}"],
    )
