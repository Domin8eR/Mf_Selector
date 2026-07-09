"""Celery task: recalculate all metrics for a category after a data promotion."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import pandas as pd
from dateutil.relativedelta import relativedelta

from app.jobs.celery_app import celery_app
from app.quant.metrics import (
    IRResult,
    daily_returns,
    improvement_metric,
    information_ratio,
    ir_slope,
    outperformance_ratio,
)

logger = logging.getLogger(__name__)

METRIC_IDS = [
    "IR_1Y", "IR_3Y", "IR_SLOPE_2Y",
    "IMPROVEMENT_METRIC", "OUTPERFORMANCE_RATIO",
]
WINDOW_YEARS = {"IR_1Y": 1, "IR_3Y": 3}
CALC_VERSION = "1.0"


def _session():
    from app.core.db import SessionLocal
    return SessionLocal()


def _load_prices(
    db,
    scheme_plan_id: str,
    start: date,
    end: date,
) -> pd.Series:
    """Load fund_nav_daily as a date-indexed Series, inner-joined to trading_calendar."""
    from sqlalchemy import text
    rows = db.execute(
        text(
            "SELECT n.date, n.nav FROM fund_nav_daily n "
            "JOIN trading_calendar tc ON tc.date = n.date "
            "WHERE n.scheme_plan_id = :sp "
            "AND n.date BETWEEN :start AND :end "
            "AND tc.is_trading_day = true "
            "ORDER BY n.date"
        ),
        {"sp": scheme_plan_id, "start": start, "end": end},
    ).fetchall()
    if not rows:
        return pd.Series(dtype=float)
    dates, navs = zip(*rows)
    return pd.Series([float(n) for n in navs], index=list(dates))


def _load_benchmark(db, benchmark_id: str, start: date, end: date) -> pd.Series:
    from sqlalchemy import text
    rows = db.execute(
        text(
            "SELECT b.date, b.value FROM benchmark_level_daily b "
            "JOIN trading_calendar tc ON tc.date = b.date "
            "WHERE b.benchmark_id = :bm "
            "AND b.date BETWEEN :start AND :end "
            "AND tc.is_trading_day = true "
            "ORDER BY b.date"
        ),
        {"bm": benchmark_id, "start": start, "end": end},
    ).fetchall()
    if not rows:
        return pd.Series(dtype=float)
    dates, values = zip(*rows)
    return pd.Series([float(v) for v in values], index=list(dates))


def _upsert_snapshot(
    db,
    scheme_plan_id: str,
    metric_id: str,
    evaluation_date: date,
    value: float | None,
    status: str,
    confidence: str,
    obs_count: int,
    win_start: date | None,
    win_end: date | None,
    data_version_id: int,
) -> None:
    from sqlalchemy import text
    db.execute(
        text(
            "INSERT INTO metric_value_snapshot "
            "(scheme_plan_id, metric_id, evaluation_date, value, status, confidence, "
            "observation_count, window_start_date, window_end_date, "
            "calculation_version, data_version_id) "
            "VALUES (:sp, :m, :d, :v, :st, :cf, :oc, :ws, :we, :cv, :dv) "
            "ON CONFLICT (scheme_plan_id, metric_id, evaluation_date) "
            "DO UPDATE SET value=EXCLUDED.value, status=EXCLUDED.status, "
            "confidence=EXCLUDED.confidence, observation_count=EXCLUDED.observation_count, "
            "window_start_date=EXCLUDED.window_start_date, "
            "window_end_date=EXCLUDED.window_end_date, "
            "calculation_version=EXCLUDED.calculation_version, "
            "data_version_id=EXCLUDED.data_version_id"
        ),
        dict(sp=scheme_plan_id, m=metric_id, d=evaluation_date, v=value,
             st=status, cf=confidence, oc=obs_count, ws=win_start,
             we=win_end, cv=CALC_VERSION, dv=data_version_id),
    )


def _upsert_rolling(
    db,
    scheme_plan_id: str,
    metric_id: str,
    evaluation_date: date,
    value: float | None,
    obs_count: int,
    win_start: date | None,
    win_end: date | None,
) -> None:
    from sqlalchemy import text
    db.execute(
        text(
            "INSERT INTO rolling_metric_value "
            "(scheme_plan_id, metric_id, evaluation_date, value, "
            "window_start_date, window_end_date, observation_count, calculation_version) "
            "VALUES (:sp, :m, :d, :v, :ws, :we, :oc, :cv) "
            "ON CONFLICT (scheme_plan_id, metric_id, evaluation_date) "
            "DO UPDATE SET value=EXCLUDED.value, "
            "window_start_date=EXCLUDED.window_start_date, "
            "window_end_date=EXCLUDED.window_end_date, "
            "observation_count=EXCLUDED.observation_count"
        ),
        dict(sp=scheme_plan_id, m=metric_id, d=evaluation_date,
             v=value, ws=win_start, we=win_end, oc=obs_count, cv=CALC_VERSION),
    )


def _compute_scheme_metrics(
    db,
    scheme_plan_id: str,
    benchmark_id: str,
    evaluation_date: date,
    data_version_id: int,
) -> dict[str, Any]:
    """Compute and upsert all metrics for one scheme plan at one evaluation date."""
    results: dict[str, Any] = {}

    # ── Rolling IR (monthly, last 36 months) ──────────────────────────────
    # Build a 3Y look-back window
    win_start = evaluation_date - relativedelta(years=3)
    fund_p = _load_prices(db, scheme_plan_id, win_start, evaluation_date)
    bm_p = _load_benchmark(db, benchmark_id, win_start, evaluation_date)

    if len(fund_p) < 2 or len(bm_p) < 2:
        for mid in METRIC_IDS:
            _upsert_snapshot(
                db, scheme_plan_id, mid, evaluation_date,
                None, "insufficient_data", "low", 0, None, None, data_version_id,
            )
        return results

    # Compute rolling 3Y IR at each month-end in the window
    rolling_ir_values: dict[date, float | None] = {}
    d = win_start + relativedelta(months=1)
    while d <= evaluation_date:
        w_end = min(d, evaluation_date)
        w_start = w_end - relativedelta(years=3)
        fp = fund_p.loc[w_start:w_end] if w_start in fund_p.index or True else fund_p
        fp = fund_p[fund_p.index >= w_start][fund_p.index <= w_end]
        bp = bm_p[bm_p.index >= w_start][bm_p.index <= w_end]
        r = information_ratio(fp, bp)
        rolling_ir_values[w_end] = r.value
        _upsert_rolling(
            db, scheme_plan_id, "IR_3Y", w_end,
            r.value, r.observation_count, r.window_start_date, r.window_end_date,
        )
        d += relativedelta(months=1)

    rolling_s = pd.Series(rolling_ir_values)

    # ── Snapshot metrics at evaluation_date ──────────────────────────────

    # 1Y IR
    ir_1y = information_ratio(
        fund_p[fund_p.index >= evaluation_date - relativedelta(years=1)],
        bm_p[bm_p.index >= evaluation_date - relativedelta(years=1)],
    )
    _upsert_snapshot(
        db, scheme_plan_id, "IR_1Y", evaluation_date,
        ir_1y.value, ir_1y.status, ir_1y.confidence,
        ir_1y.observation_count, ir_1y.window_start_date,
        ir_1y.window_end_date, data_version_id,
    )

    # 3Y IR (full window)
    ir_3y = information_ratio(fund_p, bm_p)
    _upsert_snapshot(
        db, scheme_plan_id, "IR_3Y", evaluation_date,
        ir_3y.value, ir_3y.status, ir_3y.confidence,
        ir_3y.observation_count, ir_3y.window_start_date,
        ir_3y.window_end_date, data_version_id,
    )

    # 2Y IR Slope
    slope_s = rolling_s.dropna()
    two_year_ago = evaluation_date - relativedelta(years=2)
    slope_input = slope_s[slope_s.index >= two_year_ago]
    slope_res = ir_slope(slope_input)
    _upsert_snapshot(
        db, scheme_plan_id, "IR_SLOPE_2Y", evaluation_date,
        slope_res.value,
        slope_res.status, "high" if slope_res.status == "ok" else "low",
        slope_res.observation_count, None, None, data_version_id,
    )

    # Improvement metric
    im = improvement_metric(rolling_s)
    _upsert_snapshot(
        db, scheme_plan_id, "IMPROVEMENT_METRIC", evaluation_date,
        im, "ok" if im is not None else "insufficient_data",
        "high" if im is not None else "low",
        0, None, None, data_version_id,
    )

    # Outperformance ratio
    opr = outperformance_ratio(rolling_s)
    _upsert_snapshot(
        db, scheme_plan_id, "OUTPERFORMANCE_RATIO", evaluation_date,
        opr, "ok" if opr is not None else "insufficient_data",
        "high" if opr is not None else "low",
        0, None, None, data_version_id,
    )

    results[scheme_plan_id] = {
        "ir_1y": ir_1y.value, "ir_3y": ir_3y.value,
        "ir_slope": slope_res.value, "improvement": im, "opr": opr,
    }
    return results


@celery_app.task(name="tasks.recalculate_metrics", bind=True, max_retries=3)
def recalculate_metrics(
    self,
    category_id: str,
    evaluation_date_iso: str,
    data_version_id: int,
) -> dict[str, Any]:
    """
    Recalculate all metrics for every active scheme_plan in a category.
    Called after a successful data promotion to production tables.
    """
    evaluation_date = date.fromisoformat(evaluation_date_iso)
    db = _session()
    try:
        from sqlalchemy import text
        plans = db.execute(
            text(
                "SELECT sp.id, sp.benchmark_id "
                "FROM scheme_plan sp "
                "WHERE sp.category_id = :cat AND sp.is_active = true"
            ),
            {"cat": category_id},
        ).fetchall()

        processed = 0
        for sp_id, bm_id in plans:
            if not bm_id:
                continue
            _compute_scheme_metrics(db, sp_id, bm_id, evaluation_date, data_version_id)
            processed += 1

        db.commit()
        logger.info(
            "metrics recalculated",
            category=category_id, eval_date=evaluation_date_iso,
            processed=processed,
        )
        return {"category": category_id, "processed": processed, "status": "ok"}
    except Exception as exc:
        db.rollback()
        logger.exception("metrics task failed", exc_info=exc)
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()
