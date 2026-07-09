"""Data quality endpoints — queries Altstreet_AI tables for real stats."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import get_db

router = APIRouter(prefix="/data-quality", tags=["data-quality"])


@router.get("/summary")
def get_summary(db: Session = Depends(get_db)) -> dict:
    total_schemes = db.execute(
        text("SELECT COUNT(*) FROM altstreet_scheme_master")
    ).scalar() or 0

    active_schemes = db.execute(
        text("SELECT COUNT(*) FROM altstreet_scheme_master WHERE status='Active'")
    ).scalar() or 0

    schemes_with_ratios = db.execute(
        text("SELECT COUNT(DISTINCT schemecode) FROM mf_ratios_defaultbm WHERE flag='A'")
    ).scalar() or 0

    schemes_with_nav = db.execute(
        text("SELECT COUNT(DISTINCT schemecode) FROM navhist")
    ).scalar() or 0

    latest_nav_date = db.execute(
        text("SELECT MAX(navdate)::date FROM navhist")
    ).scalar()

    latest_ratio_date = db.execute(
        text("SELECT MAX(upddate)::date FROM mf_ratios_defaultbm WHERE flag='A'")
    ).scalar()

    # Coverage % per domain
    schemes_with_cagr = db.execute(
        text("SELECT COUNT(DISTINCT schemecode::integer) FROM mf_cagr_return WHERE flag='A'")
    ).scalar() or 0

    schemes_with_aum = db.execute(
        text("SELECT COUNT(DISTINCT schemecode) FROM scheme_aum")
    ).scalar() or 0

    return {
        "total_exceptions": 0,
        "blocking_open": 0,
        "warning_open": 0,
        "nav_coverage_pct": round(100 * schemes_with_nav / max(active_schemes, 1), 1),
        "last_nav_date": str(latest_nav_date) if latest_nav_date else None,
        "last_ratio_date": str(latest_ratio_date) if latest_ratio_date else None,
        "domains": {
            "schemes": {
                "label": "Total Schemes",
                "pct": round(100 * active_schemes / max(total_schemes, 1), 1),
                "count": active_schemes,
                "total": total_schemes,
            },
            "ratios": {
                "label": "Ratios Coverage",
                "pct": round(100 * schemes_with_ratios / max(active_schemes, 1), 1),
                "count": schemes_with_ratios,
                "total": active_schemes,
            },
            "returns": {
                "label": "CAGR Returns",
                "pct": round(100 * schemes_with_cagr / max(active_schemes, 1), 1),
                "count": schemes_with_cagr,
                "total": active_schemes,
            },
            "aum": {
                "label": "AUM Data",
                "pct": round(100 * schemes_with_aum / max(active_schemes, 1), 1),
                "count": schemes_with_aum,
                "total": active_schemes,
            },
        },
    }


@router.get("/exceptions")
def get_exceptions(
    severity: str | None = Query(default=None),
    status: str | None = Query(default=None),
    domain: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    # Detect schemes with no ratios as a data quality signal
    rows = db.execute(text(
        "SELECT sm.scheme_id, sm.scheme_name, sm.category "
        "FROM altstreet_scheme_master sm "
        "WHERE sm.status='Active' "
        "AND NOT EXISTS (SELECT 1 FROM mf_ratios_defaultbm r WHERE r.schemecode=sm.scheme_id::integer AND r.flag='A') "
        "LIMIT :lim OFFSET :off"
    ), {"lim": page_size, "off": (page - 1) * page_size}).fetchall()

    total = db.execute(text(
        "SELECT COUNT(*) FROM altstreet_scheme_master sm "
        "WHERE sm.status='Active' "
        "AND NOT EXISTS (SELECT 1 FROM mf_ratios_defaultbm r WHERE r.schemecode=sm.scheme_id::integer AND r.flag='A')"
    )).scalar() or 0

    return {
        "total": total,
        "items": [
            {
                "id": i + 1,
                "domain": "ratios",
                "severity": "warning",
                "status": "open",
                "scheme_plan_id": str(r[0]),
                "benchmark_id": None,
                "affected_date": None,
                "message": f"{r[1]} — no ratio data (Sharpe/Alpha) available",
                "created_at": None,
            }
            for i, r in enumerate(rows)
        ],
    }


@router.get("/benchmark-coverage")
def benchmark_coverage(db: Session = Depends(get_db)) -> dict:
    rows = db.execute(text(
        "SELECT sm.category, COUNT(*) AS total, COUNT(r.schemecode) AS with_ratios "
        "FROM altstreet_scheme_master sm "
        "LEFT JOIN mf_ratios_defaultbm r ON r.schemecode=sm.scheme_id::integer AND r.flag='A' "
        "WHERE sm.status='Active' AND sm.category IS NOT NULL AND sm.category != '' "
        "GROUP BY sm.category ORDER BY with_ratios DESC LIMIT 15"
    )).fetchall()

    return {
        "coverage": [
            {
                "category": r[0],
                "total": r[1],
                "mapped": r[2],
                "pct": round(100.0 * r[2] / r[1], 1) if r[1] > 0 else 0.0,
            }
            for r in rows
        ]
    }


@router.get("/audit-events")
def audit_events(
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    # Return ETL run log as audit events if available
    rows = db.execute(text(
        "SELECT 'etl_run' AS action, 'ingestion' AS entity_type, "
        "       log_id::text AS entity_id, status AS detail, started_at "
        "FROM etl_run_log "
        "ORDER BY started_at DESC LIMIT :lim"
    ), {"lim": limit}).fetchall()

    return {
        "events": [
            {
                "action": r[0],
                "entity_type": r[1],
                "entity_id": r[2],
                "detail": r[3],
                "created_at": r[4].isoformat() if r[4] else None,
                "actor_name": "ETL System",
            }
            for r in rows
        ]
    }


@router.get("/ingestion-status")
def ingestion_status(db: Session = Depends(get_db)) -> dict:
    rows = db.execute(text(
        "SELECT log_id::text, status, started_at, finished_at, rows_loaded, 0 "
        "FROM etl_run_log ORDER BY started_at DESC LIMIT 10"
    )).fetchall()
    return {
        "runs": [
            {
                "source": f"ETL Run #{r[0]}",
                "status": r[1] or "completed",
                "started_at": r[2].isoformat() if r[2] else None,
                "completed_at": None,
                "rows_ingested": 0,
                "rows_failed": 0,
            }
            for r in rows
        ]
    }
