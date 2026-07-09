"""Scheme (fund) endpoints — queries Altstreet_AI existing tables directly."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import get_db

router = APIRouter(prefix="/schemes", tags=["schemes"])

_SCHEME_SELECT = """
    SELECT
        sm.scheme_id,
        sm.scheme_name,
        COALESCE(a.s_name, sm.amc::text) AS amc_name,
        sm.category,
        sm.sub_category,
        sm.aum,
        sm.launch_date::date AS launch_date,
        sm.status,
        sm.isin,
        sm.amfi_code
    FROM altstreet_scheme_master sm
    LEFT JOIN amc_mst_new a ON a.amc_code = sm.amc::integer
"""


def _row_to_dict(r) -> dict:
    return {
        "id": str(r[0]),
        "fund_name": r[1],
        "amc_name": r[2] or "",
        "category": r[3] or "",
        "sub_category": r[4] or "",
        "aum_cr": round(float(r[5]) / 100, 2) if r[5] else None,  # lakhs → crores
        "launch_date": str(r[6]) if r[6] else None,
        "status": r[7] or "",
        "isin": r[8] or "",
        "amfi_code": r[9] or "",
        "plan_type": "growth",
        "option_type": "direct",
        "is_active": (r[7] or "").lower() == "active",
        "benchmark_id": None,
        "expense_ratio_pct": None,
    }


@router.get("/categories")
def list_categories(db: Session = Depends(get_db)) -> dict:
    """Return distinct fund categories with counts — used to populate the rankings filter."""
    rows = db.execute(text(
        "SELECT category, COUNT(*) AS total "
        "FROM altstreet_scheme_master "
        "WHERE status='Active' AND category IS NOT NULL AND category != '' "
        "GROUP BY category ORDER BY total DESC LIMIT 30"
    )).fetchall()
    return {
        "categories": [
            {"id": r[0], "name": r[0], "count": r[1]}
            for r in rows
        ]
    }


@router.get("/categories-36")
def list_categories_36(db: Session = Depends(get_db)) -> list[dict]:
    """Return the 36-bucket category taxonomy grouped by ALL Equity / ALL Hybrid / ALL Passive.

    Reads from category_taxonomy_current (versioned view built by
    scripts/step3_final_category_taxonomy.py).  Returns null if the
    taxonomy table doesn't exist yet — callers should fall back to /categories.
    """
    try:
        rows = db.execute(text("""
            SELECT bucket_group, bucket_36, COUNT(*) AS cnt
            FROM category_taxonomy_current
            WHERE bucket_36 IS NOT NULL
            GROUP BY bucket_group, bucket_36
            ORDER BY bucket_group, cnt DESC
        """)).fetchall()
    except Exception:
        return []

    groups: dict[str, list[dict]] = {}
    for group, bucket, cnt in rows:
        groups.setdefault(group, []).append({"id": bucket, "name": bucket, "count": int(cnt)})

    # Stable group order
    _ORDER = ["ALL Equity", "ALL Hybrid", "ALL Passive"]
    return [
        {"group": g, "buckets": groups[g]}
        for g in _ORDER
        if g in groups
    ] + [
        {"group": g, "buckets": v}
        for g, v in groups.items()
        if g not in _ORDER
    ]


@router.get("")
def list_schemes(
    category: str | None = Query(default=None),
    status: str = Query(default="Active"),
    search: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    where = ["(sm.status = :status OR :status = 'all')"]
    params: dict = {"status": status}

    if category:
        where.append("sm.category = :category")
        params["category"] = category
    if search:
        where.append("(sm.scheme_name ILIKE :search OR a.s_name ILIKE :search)")
        params["search"] = f"%{search}%"

    where_sql = "WHERE " + " AND ".join(where)
    count_q = f"SELECT COUNT(*) FROM altstreet_scheme_master sm LEFT JOIN amc_mst_new a ON a.amc_code = sm.amc::integer {where_sql}"
    total = db.execute(text(count_q), params).scalar() or 0

    select_q = f"{_SCHEME_SELECT} {where_sql} ORDER BY sm.scheme_name LIMIT :limit OFFSET :offset"
    params["limit"] = page_size
    params["offset"] = (page - 1) * page_size
    rows = db.execute(text(select_q), params).fetchall()

    return {
        "items": [_row_to_dict(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{scheme_id}")
def get_scheme(scheme_id: str, db: Session = Depends(get_db)) -> dict:
    row = db.execute(
        text(f"{_SCHEME_SELECT} WHERE sm.scheme_id = :id"),
        {"id": scheme_id},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Scheme '{scheme_id}' not found")
    return _row_to_dict(row)


@router.get("/{scheme_id}/holdings")
def scheme_holdings(
    scheme_id: str,
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
) -> dict:
    """
    Top holdings from selfmade_portfolio_holding (most recent date).
    Falls back to altstreet_scheme_holdings if selfmade table has no data.
    """
    # Try selfmade holdings first
    date_row = db.execute(text("""
        SELECT MAX(as_of_date) FROM selfmade_portfolio_holding
        WHERE scheme_id = :sc
    """), {"sc": int(scheme_id)}).fetchone()
    holdings_date = date_row[0] if date_row else None

    if holdings_date:
        rows = db.execute(text("""
            SELECT sm.company_name, sm.sector, sm.market_cap_bucket,
                   ph.holding_weight_pct
            FROM selfmade_portfolio_holding ph
            JOIN selfmade_security_master sm ON sm.id = ph.security_id
            WHERE ph.scheme_id = :sc AND ph.as_of_date = :dt
            ORDER BY ph.holding_weight_pct DESC
            LIMIT :lim
        """), {"sc": int(scheme_id), "dt": holdings_date, "lim": limit}).fetchall()

        total_wt = db.execute(text("""
            SELECT SUM(holding_weight_pct)
            FROM selfmade_portfolio_holding
            WHERE scheme_id = :sc AND as_of_date = :dt
        """), {"sc": int(scheme_id), "dt": holdings_date}).scalar()

        return {
            "scheme_plan_id": scheme_id,
            "as_of_date": str(holdings_date),
            "source": "selfmade",
            "total_weight_pct": round(float(total_wt or 0), 2),
            "holdings": [
                {
                    "company_name": r[0],
                    "sector": r[1],
                    "market_cap_bucket": r[2],
                    "weight_pct": round(float(r[3] or 0), 4),
                }
                for r in rows
            ],
        }

    # Fallback to old vendor table
    rows = db.execute(text("""
        SELECT company_name, weight, NULL AS sector, NULL AS mktcap
        FROM altstreet_scheme_holdings
        WHERE scheme_id = :id
        ORDER BY weight DESC NULLS LAST LIMIT :lim
    """), {"id": scheme_id, "lim": limit}).fetchall()

    return {
        "scheme_plan_id": scheme_id,
        "as_of_date": None,
        "source": "vendor",
        "total_weight_pct": None,
        "holdings": [
            {
                "company_name": r[0],
                "sector": r[2],
                "market_cap_bucket": r[3],
                "weight_pct": round(float(r[1]), 4) if r[1] else None,
            }
            for r in rows
        ],
    }


@router.get("/{scheme_id}/documents")
def scheme_documents(
    scheme_id: str,
    db: Session = Depends(get_db),
) -> dict:
    """Fund documents from selfmade_document (metadata only, no RAG)."""
    rows = db.execute(text("""
        SELECT doc_type, as_of_date, file_url, extraction_status
        FROM selfmade_document
        WHERE scheme_id = :sc
        ORDER BY as_of_date DESC
    """), {"sc": int(scheme_id)}).fetchall()

    _LABELS = {
        "factsheet": "Fact Sheet",
        "holdings": "Portfolio Holdings",
        "sid": "Scheme Information Document",
    }

    return {
        "scheme_plan_id": scheme_id,
        "documents": [
            {
                "doc_type": r[0],
                "label": _LABELS.get(r[0], r[0]),
                "as_of_date": str(r[1]),
                "file_url": r[2],
                "extraction_status": r[3],
            }
            for r in rows
        ],
    }
