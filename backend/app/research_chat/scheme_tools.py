from __future__ import annotations
from .tool_result import ToolResult
from .db import execute_query
from .schema_adapter import get_table, col
from .amc_codes import resolve_name, resolve_codes

COLUMNS = ["scheme_id", "scheme_name", "amfi_code", "isin", "amc",
           "category", "sub_category", "aum", "launch_date", "status"]


def _resolve_rows(rows: list[dict]) -> list[dict]:
    for r in rows:
        if "amc" in r:
            r["amc"] = resolve_name(r["amc"])
    return rows


def _build_where(filters: dict) -> tuple[str, dict]:
    t = "scheme_master"
    clauses: list[str] = []
    params: dict = {}

    if filters.get("amc"):
        amc_raw = filters["amc"]
        codes = resolve_codes(amc_raw)
        if codes:
            placeholders = ", ".join(f":amc_code{i}" for i, _ in enumerate(codes))
            clauses.append(
                f"({col(t,'amc')} IN ({placeholders}) "
                f"OR {col(t,'scheme_name')} ILIKE :amc_name)"
            )
            params["amc_name"] = f"%{amc_raw}%"
            for i, code in enumerate(codes):
                params[f"amc_code{i}"] = code
        else:
            clauses.append(
                f"({col(t,'amc')} ILIKE :amc OR {col(t,'scheme_name')} ILIKE :amc)"
            )
            params["amc"] = f"%{amc_raw}%"

    if filters.get("category"):
        clauses.append(
            f"({col(t,'category')} ILIKE :category "
            f"OR COALESCE({col(t,'sub_category')}, '') ILIKE :category)"
        )
        params["category"] = f"%{filters['category']}%"

    if filters.get("sub_category"):
        clauses.append(f"{col(t,'sub_category')} ILIKE :sub_cat")
        params["sub_cat"] = f"%{filters['sub_category']}%"

    if filters.get("status"):
        clauses.append(f"{col(t,'status')} ILIKE :status")
        params["status"] = filters["status"]
    elif not filters.get("amc"):
        clauses.append(f"{col(t,'status')} = :status")
        params["status"] = "Active"

    if filters.get("aum_min") is not None:
        clauses.append(f"{col(t,'aum')} >= :aum_min")
        params["aum_min"] = float(filters["aum_min"])

    if filters.get("aum_max") is not None:
        clauses.append(f"{col(t,'aum')} <= :aum_max")
        params["aum_max"] = float(filters["aum_max"])

    if filters.get("launch_date_before"):
        clauses.append(f"{col(t,'launch_date')} < :launch_before")
        params["launch_before"] = filters["launch_date_before"]

    if filters.get("launch_date_after"):
        clauses.append(f"{col(t,'launch_date')} > :launch_after")
        params["launch_after"] = filters["launch_date_after"]

    where = " AND ".join(clauses) if clauses else "1=1"
    return where, params


def list_schemes(filters: dict | None = None) -> ToolResult:
    filters = filters or {}
    where, params = _build_where(filters)
    t = get_table("scheme_master")
    rows = _resolve_rows(execute_query(
        f"SELECT * FROM {t} WHERE {where} ORDER BY scheme_name", params
    ))
    desc = ", ".join(f"{k}={v}" for k, v in filters.items()) or "none"
    return ToolResult(
        narrative_summary=f"Found {len(rows)} scheme(s) matching filters: {desc}.",
        table=rows, columns=COLUMNS,
        citations=[f"altstreet_scheme_master | filters: {desc}"],
    )


def count_schemes(filters: dict | None = None) -> ToolResult:
    filters = filters or {}
    where, params = _build_where(filters)
    t = get_table("scheme_master")
    rows = execute_query(f"SELECT COUNT(*) AS cnt FROM {t} WHERE {where}", params)
    total = rows[0]["cnt"] if rows else 0
    return ToolResult(
        narrative_summary=f"Total schemes matching: {total}.",
        table=[{"count": total}], columns=["count"],
        citations=[f"altstreet_scheme_master | count | filters: {filters}"],
    )


def group_by_amc(filters: dict | None = None) -> ToolResult:
    filters = filters or {}
    where, params = _build_where(filters)
    t = get_table("scheme_master")
    rows = execute_query(f"SELECT amc FROM {t} WHERE {where}", params)
    groups: dict[str, int] = {}
    for r in rows:
        name = resolve_name(r.get("amc", "Unknown"))
        groups[name] = groups.get(name, 0) + 1
    table = [{"amc": k, "scheme_count": v} for k, v in sorted(groups.items())]
    return ToolResult(
        narrative_summary=f"Schemes grouped by AMC ({len(groups)} AMCs).",
        table=table, columns=["amc", "scheme_count"],
        citations=["altstreet_scheme_master | group by amc"],
    )


def sort_schemes(
    filters: dict | None = None,
    sort_by: str = "aum",
    sort_dir: str = "desc",
    limit: int | None = None,
) -> ToolResult:
    filters = filters or {}
    where, params = _build_where(filters)
    t = get_table("scheme_master")
    direction = "DESC" if sort_dir.lower() == "desc" else "ASC"
    sql = f"SELECT * FROM {t} WHERE {where} ORDER BY {sort_by} {direction}"
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = _resolve_rows(execute_query(sql, params))
    label = f" (top {limit})" if limit else ""
    return ToolResult(
        narrative_summary=f"Schemes sorted by {sort_by} ({sort_dir}){label}. {len(rows)} results.",
        table=rows, columns=COLUMNS,
        citations=[f"altstreet_scheme_master | sort: {sort_by} {sort_dir}"],
    )
