"""
seed_db.py — populate the dev DB with realistic synthetic data.

Creates per category (Large Cap, Mid Cap, Small Cap):
  - Category master row
  - Benchmark + daily levels/returns
  - 8 funds with 5Y synthetic NAV history
  - Daily returns and excess returns vs category benchmark
  - Rolling 3Y IR snapshots (monthly, last 36 months)
  - Metric value snapshots (1Y IR, 3Y IR, 2Y IR Slope,
    Improvement Metric, Outperformance Ratio)
  - One default rule set + rule version + 4 rule components
  - One ranking run + ranked results

Usage (run with Docker Compose up):
    cd /Users/piyushrajlenka/Mf_Selector
    python scripts/seed_db.py

The script is idempotent — safe to run multiple times.
"""

import os
import random
import sys
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

# Allow importing app modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.models import (  # noqa: E402
    AMC,
    Benchmark,
    BenchmarkLevelDaily,
    BenchmarkReturnDaily,
    Category,
    DataVersion,
    DataVersionStatus,
    ExcessReturnDaily,
    FundNavDaily,
    FundReturnDaily,
    MetricDefinition,
    MetricValueSnapshot,
    RankingComponentContribution,
    RankingResult,
    RankingRun,
    RollingMetricValue,
    RuleComponent,
    RuleSet,
    RuleVersion,
    RuleVersionStatus,
    Scheme,
    SchemePlan,
    TradingCalendar,
)

# ── Config ──────────────────────────────────────────────────────────────────

_env_path = os.path.join(os.path.dirname(__file__), "..", "backend", ".env")
if os.path.exists(_env_path) and "DATABASE_URL" not in os.environ:
    with open(_env_path, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://postgres:@localhost:5432/altstreet"
)
random.seed(42)
np.random.seed(42)

START_DATE = date(2020, 1, 1)
END_DATE = date(2024, 11, 30)
EVAL_DATE = END_DATE
ANNUALISE = 252
MIN_OBS = 63
CALC_VERSION = "1.0"

# ── Category universe definitions ────────────────────────────────────────────
#
# rc_prefix: prefix for RuleComponent IDs to avoid PK collisions across categories.
# Large Cap uses "" (no prefix) to stay backwards-compatible with existing seed rows.

CATEGORY_CONFIGS: list[dict[str, Any]] = [
    {
        "id": "LARGE_CAP",
        "name": "Large Cap",
        "sebi_name": "Large Cap Fund",
        "bm_id": "NIFTY50-TRI",
        "bm_name": "Nifty 50 TRI",
        "bm_index_family": "NIFTY",
        "bm_drift": 0.120,
        "bm_vol": 0.185,
        "bm_start": 18000.0,
        "rule_set_id": "CLIENT-DEFAULT-LC",
        "rule_version_id": "RV-LC-V32",
        "rule_set_name": "Client Default — Large Cap",
        "rule_version_number": 32,
        "ranking_run_id": "RR-LC-20241130",
        "rc_prefix": "",       # keep original IDs for backwards compat
        "funds": [
            {"id": "HDFC-LC-D-G",   "name": "HDFC Top 100 Fund",                  "amc": "HDFC AMC",             "drift": 0.140, "vol": 0.190, "aum": 24300, "er": 0.89},
            {"id": "ICICI-BC-D-G",  "name": "ICICI Pru Bluechip Fund",             "amc": "ICICI Prudential AMC", "drift": 0.130, "vol": 0.180, "aum": 44200, "er": 0.85},
            {"id": "AXIS-BC-D-G",   "name": "Axis Bluechip Fund",                  "amc": "Axis AMC",             "drift": 0.120, "vol": 0.200, "aum": 17100, "er": 0.91},
            {"id": "SBI-BC-D-G",    "name": "SBI Bluechip Fund",                   "amc": "SBI MF",               "drift": 0.110, "vol": 0.210, "aum": 43600, "er": 0.76},
            {"id": "KOTAK-BC-D-G",  "name": "Kotak Bluechip Fund",                 "amc": "Kotak MF",             "drift": 0.100, "vol": 0.220, "aum":  7800, "er": 0.93},
            {"id": "MIRAE-LC-D-G",  "name": "Mirae Asset Large Cap Fund",          "amc": "Mirae Asset MF",       "drift": 0.125, "vol": 0.185, "aum": 35800, "er": 0.54},
            {"id": "NIPPON-LC-D-G", "name": "Nippon India Large Cap Fund",         "amc": "Nippon MF",            "drift": 0.115, "vol": 0.195, "aum": 26100, "er": 0.95},
            {"id": "CANARA-LC-D-G", "name": "Canara Robeco Bluechip Equity Fund",  "amc": "Canara Robeco MF",     "drift": 0.130, "vol": 0.185, "aum": 11200, "er": 0.41},
        ],
    },
    {
        "id": "MID_CAP",
        "name": "Mid Cap",
        "sebi_name": "Mid Cap Fund",
        "bm_id": "NIFTY-MIDCAP150-TRI",
        "bm_name": "Nifty Midcap 150 TRI",
        "bm_index_family": "NIFTY",
        "bm_drift": 0.155,
        "bm_vol": 0.240,
        "bm_start": 12000.0,
        "rule_set_id": "CLIENT-DEFAULT-MC",
        "rule_version_id": "RV-MC-V32",
        "rule_set_name": "Client Default — Mid Cap",
        "rule_version_number": 32,
        "ranking_run_id": "RR-MC-20241130",
        "rc_prefix": "MC-",
        "funds": [
            {"id": "HDFC-MC-D-G",    "name": "HDFC Mid-Cap Opportunities Fund",  "amc": "HDFC AMC",              "drift": 0.175, "vol": 0.250, "aum": 62000, "er": 0.79},
            {"id": "NIPPON-MC-D-G",  "name": "Nippon India Growth Fund",         "amc": "Nippon MF",             "drift": 0.165, "vol": 0.260, "aum": 25600, "er": 0.88},
            {"id": "KOTAK-MC-D-G",   "name": "Kotak Emerging Equity Fund",       "amc": "Kotak MF",             "drift": 0.170, "vol": 0.245, "aum": 39400, "er": 0.44},
            {"id": "AXIS-MC-D-G",    "name": "Axis Midcap Fund",                 "amc": "Axis AMC",              "drift": 0.160, "vol": 0.255, "aum": 24800, "er": 0.56},
            {"id": "SBI-MC-D-G",     "name": "SBI Magnum Midcap Fund",           "amc": "SBI MF",               "drift": 0.155, "vol": 0.265, "aum": 17200, "er": 0.83},
            {"id": "DSP-MC-D-G",     "name": "DSP Midcap Fund",                  "amc": "DSP MF",               "drift": 0.162, "vol": 0.252, "aum": 14800, "er": 0.67},
            {"id": "FRANKLIN-MC-D-G","name": "Franklin India Prima Fund",        "amc": "Franklin Templeton MF", "drift": 0.168, "vol": 0.258, "aum":  9600, "er": 0.92},
            {"id": "MOTILAL-MC-D-G", "name": "Motilal Oswal Midcap Fund",        "amc": "Motilal Oswal MF",     "drift": 0.180, "vol": 0.270, "aum": 20400, "er": 0.61},
        ],
    },
    {
        "id": "SMALL_CAP",
        "name": "Small Cap",
        "sebi_name": "Small Cap Fund",
        "bm_id": "NIFTY-SMALLCAP250-TRI",
        "bm_name": "Nifty Smallcap 250 TRI",
        "bm_index_family": "NIFTY",
        "bm_drift": 0.180,
        "bm_vol": 0.300,
        "bm_start": 8000.0,
        "rule_set_id": "CLIENT-DEFAULT-SC",
        "rule_version_id": "RV-SC-V32",
        "rule_set_name": "Client Default — Small Cap",
        "rule_version_number": 32,
        "ranking_run_id": "RR-SC-20241130",
        "rc_prefix": "SC-",
        "funds": [
            {"id": "NIPPON-SC-D-G",  "name": "Nippon India Small Cap Fund",     "amc": "Nippon MF",         "drift": 0.200, "vol": 0.320, "aum": 54000, "er": 0.68},
            {"id": "SBI-SC-D-G",     "name": "SBI Small Cap Fund",              "amc": "SBI MF",            "drift": 0.195, "vol": 0.310, "aum": 27400, "er": 0.62},
            {"id": "AXIS-SC-D-G",    "name": "Axis Small Cap Fund",             "amc": "Axis AMC",          "drift": 0.188, "vol": 0.315, "aum": 20600, "er": 0.59},
            {"id": "KOTAK-SC-D-G",   "name": "Kotak Small Cap Fund",            "amc": "Kotak MF",          "drift": 0.192, "vol": 0.325, "aum": 12800, "er": 0.71},
            {"id": "HDFC-SC-D-G",    "name": "HDFC Small Cap Fund",             "amc": "HDFC AMC",          "drift": 0.185, "vol": 0.305, "aum": 28600, "er": 0.65},
            {"id": "DSP-SC-D-G",     "name": "DSP Small Cap Fund",              "amc": "DSP MF",            "drift": 0.190, "vol": 0.318, "aum":  9200, "er": 0.88},
            {"id": "QUANT-SC-D-G",   "name": "Quant Small Cap Fund",            "amc": "Quant MF",          "drift": 0.210, "vol": 0.335, "aum": 18700, "er": 0.72},
            {"id": "CANARA-SC-D-G",  "name": "Canara Robeco Small Cap Fund",    "amc": "Canara Robeco MF",  "drift": 0.182, "vol": 0.308, "aum":  8400, "er": 0.55},
        ],
    },
]

# ── Helpers ──────────────────────────────────────────────────────────────────


def gbm_series(start: float, drift: float, vol: float, n: int) -> np.ndarray:
    """Geometric Brownian Motion daily prices (annualised parameters)."""
    daily_drift = drift / ANNUALISE
    daily_vol = vol / (ANNUALISE ** 0.5)
    shocks = np.random.normal(daily_drift, daily_vol, n)
    log_returns = np.cumsum(np.log(1 + shocks))
    return start * np.exp(log_returns)


def trading_days(start: date, end: date) -> list[date]:
    """Mon-Fri dates in [start, end] — no holiday calendar for seed data."""
    out = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def annualised_return(prices: pd.Series) -> float:
    n = len(prices) - 1
    if n < 1:
        return float("nan")
    return float((prices.iloc[-1] / prices.iloc[0]) ** (ANNUALISE / n) - 1)


def tracking_error(excess: pd.Series) -> float:
    if len(excess) < 4:
        return float("nan")
    return float(excess.std(ddof=1) * (ANNUALISE ** 0.5))


def information_ratio(fund_prices: pd.Series, bm_prices: pd.Series) -> float | None:
    fund_ret = fund_prices.pct_change().dropna()
    bm_ret = bm_prices.pct_change().dropna()
    aligned = pd.concat([fund_ret, bm_ret], axis=1).dropna()
    aligned.columns = ["f", "b"]
    if len(aligned) < MIN_OBS:
        return None
    excess = aligned["f"] - aligned["b"]
    ar_f = annualised_return(fund_prices)
    ar_b = annualised_return(bm_prices)
    aer = ar_f - ar_b
    te = tracking_error(excess)
    if te == 0 or np.isnan(te):
        return None
    return aer / te


def _window_ir(
    price_s: pd.Series,
    bm_series_pd: pd.Series,
    years: int,
) -> float | None:
    w = date(EVAL_DATE.year - years, EVAL_DATE.month, 1)
    fp = price_s.loc[max(w, START_DATE):EVAL_DATE]
    bp = bm_series_pd.loc[fp.index[0]:fp.index[-1]]
    return information_ratio(fp, bp)


# ── Per-category seeder ───────────────────────────────────────────────────────


def seed_category(
    db: Session,
    cfg: dict[str, Any],
    dv: DataVersion,
    td_dates: list[date],
    eval_months: list[date],
) -> None:
    cat_id = cfg["id"]
    bm_id = cfg["bm_id"]
    rule_set_id = cfg["rule_set_id"]
    rule_version_id = cfg["rule_version_id"]
    ranking_run_id = cfg["ranking_run_id"]
    rc_prefix = cfg["rc_prefix"]

    print(f"\n── {cfg['name']} ────────────────────────────────────────────")

    # ── Category ─────────────────────────────────────────────────────────────
    if db.get(Category, cat_id) is None:
        db.add(Category(
            id=cat_id,
            name=cfg["name"],
            sebi_name=cfg["sebi_name"],
            asset_class="equity",
        ))
        db.flush()
    print(f"  ✓ category ({cfg['name']})")

    # ── Benchmark ─────────────────────────────────────────────────────────────
    if db.get(Benchmark, bm_id) is None:
        db.add(Benchmark(
            id=bm_id,
            name=cfg["bm_name"],
            index_family=cfg["bm_index_family"],
            index_type="TRI",
        ))
        db.flush()

    bm_prices_arr = gbm_series(cfg["bm_start"], cfg["bm_drift"], cfg["bm_vol"], len(td_dates))
    bm_series_pd = pd.Series(bm_prices_arr, index=td_dates)

    existing_bm_navs = {
        r[0] for r in db.execute(
            text("SELECT date FROM benchmark_level_daily WHERE benchmark_id = :b"),
            {"b": bm_id},
        ).fetchall()
    }
    new_bm_navs = [
        BenchmarkLevelDaily(
            benchmark_id=bm_id, date=d,
            value=float(bm_series_pd[d]), data_version_id=dv.id,
        )
        for d in td_dates if d not in existing_bm_navs
    ]
    if new_bm_navs:
        db.bulk_save_objects(new_bm_navs)
        db.flush()

    bm_ret_arr = bm_series_pd.pct_change().dropna()
    existing_bm_rets = {
        r[0] for r in db.execute(
            text("SELECT date FROM benchmark_return_daily WHERE benchmark_id = :b"),
            {"b": bm_id},
        ).fetchall()
    }
    new_bm_rets = [
        BenchmarkReturnDaily(benchmark_id=bm_id, date=d, daily_return=float(bm_ret_arr[d]))
        for d in bm_ret_arr.index if d not in existing_bm_rets
    ]
    if new_bm_rets:
        db.bulk_save_objects(new_bm_rets)
        db.flush()
    print(f"  ✓ benchmark NAV + returns ({cfg['bm_name']}, {len(td_dates)} rows)")

    # ── AMC + Scheme + SchemePlan ─────────────────────────────────────────────
    amc_ids: dict[str, str] = {}
    for f in cfg["funds"]:
        amc_id = f["amc"].lower().replace(" ", "-")
        amc_ids[f["id"]] = amc_id
        if db.get(AMC, amc_id) is None:
            db.add(AMC(id=amc_id, name=f["amc"], short_name=f["amc"].split()[0]))
    db.flush()

    for f in cfg["funds"]:
        scheme_id = f["id"].rsplit("-", 2)[0]
        if db.get(Scheme, scheme_id) is None:
            db.add(Scheme(id=scheme_id, amc_id=amc_ids[f["id"]], name=f["name"]))
        if db.get(SchemePlan, f["id"]) is None:
            db.add(SchemePlan(
                id=f["id"],
                scheme_id=scheme_id,
                category_id=cat_id,
                benchmark_id=bm_id,
                plan_type="growth",
                option_type="direct",
                aum_cr=f["aum"],
                expense_ratio_pct=f["er"],
                launch_date=date(2003, 1, 1),
                is_active=True,
            ))
    db.flush()
    print(f"  ✓ AMC / Scheme / SchemePlan ({len(cfg['funds'])} funds)")

    # ── Fund NAVs + returns + excess returns ──────────────────────────────────
    fund_price_series: dict[str, pd.Series] = {}
    for f in cfg["funds"]:
        sp_id = f["id"]
        prices_arr = gbm_series(100.0, f["drift"], f["vol"], len(td_dates))
        price_s = pd.Series(prices_arr, index=td_dates)
        fund_price_series[sp_id] = price_s

        existing_navs = {
            r[0] for r in db.execute(
                text("SELECT date FROM fund_nav_daily WHERE scheme_plan_id = :s"),
                {"s": sp_id},
            ).fetchall()
        }
        new_navs = [
            FundNavDaily(scheme_plan_id=sp_id, date=d,
                         nav=round(float(price_s[d]), 6), data_version_id=dv.id)
            for d in td_dates if d not in existing_navs
        ]
        if new_navs:
            db.bulk_save_objects(new_navs)

        ret_arr = price_s.pct_change().dropna()
        existing_rets = {
            r[0] for r in db.execute(
                text("SELECT date FROM fund_return_daily WHERE scheme_plan_id = :s"),
                {"s": sp_id},
            ).fetchall()
        }
        new_rets = [
            FundReturnDaily(scheme_plan_id=sp_id, date=d, daily_return=float(ret_arr[d]))
            for d in ret_arr.index if d not in existing_rets
        ]
        if new_rets:
            db.bulk_save_objects(new_rets)

        exc_arr = ret_arr - bm_ret_arr.reindex(ret_arr.index).fillna(0)
        existing_exc = {
            r[0] for r in db.execute(
                text("SELECT date FROM excess_return_daily "
                     "WHERE scheme_plan_id = :s AND benchmark_id = :b"),
                {"s": sp_id, "b": bm_id},
            ).fetchall()
        }
        new_exc = [
            ExcessReturnDaily(
                scheme_plan_id=sp_id, benchmark_id=bm_id,
                date=d, excess_return=float(exc_arr[d]),
            )
            for d in exc_arr.index if d not in existing_exc
        ]
        if new_exc:
            db.bulk_save_objects(new_exc)
    db.flush()
    print(f"  ✓ fund NAV + returns + excess returns ({len(cfg['funds'])} funds)")

    # ── Rolling 3Y IR ─────────────────────────────────────────────────────────
    for sp_id, price_s in fund_price_series.items():
        existing_rmv = {
            r[0] for r in db.execute(
                text("SELECT evaluation_date FROM rolling_metric_value "
                     "WHERE scheme_plan_id = :s AND metric_id = 'IR_3Y'"),
                {"s": sp_id},
            ).fetchall()
        }
        for ev in eval_months:
            if ev in existing_rmv:
                continue
            w_start = date(ev.year - 3, ev.month, 1)
            fp = price_s.loc[w_start:ev] if w_start >= START_DATE else price_s.loc[:ev]
            bp = bm_series_pd.loc[fp.index[0]:fp.index[-1]]
            ir = information_ratio(fp, bp)
            db.add(RollingMetricValue(
                scheme_plan_id=sp_id,
                metric_id="IR_3Y",
                evaluation_date=ev,
                value=ir,
                window_start_date=fp.index[0] if len(fp) else None,
                window_end_date=fp.index[-1] if len(fp) else None,
                observation_count=len(fp),
                calculation_version=CALC_VERSION,
            ))
    db.flush()
    print(f"  ✓ rolling IR_3Y ({len(eval_months)} months × {len(cfg['funds'])} funds)")

    # ── Metric value snapshots ────────────────────────────────────────────────
    metric_rows: list[MetricValueSnapshot] = []
    fund_metric_vals: dict[str, dict[str, float | None]] = {}

    for f in cfg["funds"]:
        sp_id = f["id"]
        price_s = fund_price_series[sp_id]
        vals: dict[str, float | None] = {}

        vals["IR_1Y"] = _window_ir(price_s, bm_series_pd, 1)
        vals["IR_3Y"] = _window_ir(price_s, bm_series_pd, 3)

        rmv_q = db.execute(
            text(
                "SELECT evaluation_date, value FROM rolling_metric_value "
                "WHERE scheme_plan_id = :s AND metric_id = 'IR_3Y' "
                "AND evaluation_date >= :start ORDER BY evaluation_date"
            ),
            {"s": sp_id, "start": date(EVAL_DATE.year - 2, EVAL_DATE.month, 1)},
        ).fetchall()
        valid_rmv = [(r[0], float(r[1])) for r in rmv_q if r[1] is not None]
        if len(valid_rmv) >= 4:
            t = list(range(len(valid_rmv)))
            y = [v[1] for v in valid_rmv]
            slope, *_ = stats.linregress(t, y)
            vals["IR_SLOPE_2Y"] = float(slope)
        else:
            vals["IR_SLOPE_2Y"] = None

        all_rmv = [
            (r[0], float(r[1]))
            for r in db.execute(
                text(
                    "SELECT evaluation_date, value FROM rolling_metric_value "
                    "WHERE scheme_plan_id = :s AND metric_id = 'IR_3Y' "
                    "AND value IS NOT NULL ORDER BY evaluation_date DESC LIMIT 24"
                ),
                {"s": sp_id},
            ).fetchall()
            if r[1] is not None
        ]
        if len(all_rmv) >= 8:
            recent = [v[1] for v in all_rmv[:12]]
            prior = [v[1] for v in all_rmv[12:24]]
            vals["IMPROVEMENT_METRIC"] = float(np.mean(recent) - np.mean(prior)) if prior else None
        else:
            vals["IMPROVEMENT_METRIC"] = None

        rolling_values = [v[1] for v in all_rmv]
        vals["OUTPERFORMANCE_RATIO"] = (
            sum(1 for v in rolling_values if v > 0) / len(rolling_values)
            if rolling_values else None
        )

        fund_metric_vals[sp_id] = vals

        for metric_id, value in vals.items():
            existing = db.execute(
                text(
                    "SELECT 1 FROM metric_value_snapshot "
                    "WHERE scheme_plan_id = :s AND metric_id = :m AND evaluation_date = :d"
                ),
                {"s": sp_id, "m": metric_id, "d": EVAL_DATE},
            ).fetchone()
            if existing is None:
                metric_rows.append(MetricValueSnapshot(
                    scheme_plan_id=sp_id,
                    metric_id=metric_id,
                    evaluation_date=EVAL_DATE,
                    value=value,
                    status="ok" if value is not None else "insufficient_data",
                    confidence="high" if value is not None else "low",
                    calculation_version=CALC_VERSION,
                    data_version_id=dv.id,
                ))
    if metric_rows:
        db.bulk_save_objects(metric_rows)
    db.flush()
    print(f"  ✓ metric_value_snapshot ({len(cfg['funds'])} funds)")

    # ── Rule set + version + components ───────────────────────────────────────
    if db.get(RuleSet, rule_set_id) is None:
        db.add(RuleSet(id=rule_set_id, name=cfg["rule_set_name"], category_id=cat_id))
    if db.get(RuleVersion, rule_version_id) is None:
        rv = RuleVersion(
            id=rule_version_id,
            rule_set_id=rule_set_id,
            version_number=cfg["rule_version_number"],
            status=RuleVersionStatus.ACTIVE,
        )
        db.add(rv)
        db.flush()
        components = [
            (f"RC-{rc_prefix}SLOPE",   "IR_SLOPE_2Y",         0.30, 1),
            (f"RC-{rc_prefix}IMPROVE", "IMPROVEMENT_METRIC",   0.30, 2),
            (f"RC-{rc_prefix}IR3Y",    "IR_3Y",                0.25, 3),
            (f"RC-{rc_prefix}OPR",     "OUTPERFORMANCE_RATIO", 0.15, 4),
        ]
        for rc_id, metric_id, weight, order in components:
            db.add(RuleComponent(
                id=rc_id,
                rule_version_id=rule_version_id,
                metric_id=metric_id,
                weight=weight,
                direction="higher_better",
                normalization="percentile_rank",
                window_years=3,
                display_order=order,
            ))
        db.execute(
            text("UPDATE rule_set SET active_version_id = :v WHERE id = :rs"),
            {"v": rule_version_id, "rs": rule_set_id},
        )
    db.flush()
    print("  ✓ rule_set + rule_version + rule_components")

    # ── Ranking run + results ─────────────────────────────────────────────────
    weights = {
        "IR_SLOPE_2Y": 0.30,
        "IMPROVEMENT_METRIC": 0.30,
        "IR_3Y": 0.25,
        "OUTPERFORMANCE_RATIO": 0.15,
    }
    metric_cols = list(weights.keys())

    if db.get(RankingRun, ranking_run_id) is None:
        db.add(RankingRun(
            id=ranking_run_id,
            rule_version_id=rule_version_id,
            category_id=cat_id,
            evaluation_date=EVAL_DATE,
            data_version_id=dv.id,
            calculation_version=CALC_VERSION,
            scheme_count=len(cfg["funds"]),
        ))
        db.flush()

        raw: dict[str, dict[str, float | None]] = {
            sp_id: {m: fund_metric_vals[sp_id].get(m) for m in metric_cols}
            for sp_id in fund_price_series
        }

        normed: dict[str, dict[str, float]] = {}
        for m in metric_cols:
            vals_list = [
                (sp_id, sp_raw[m])
                for sp_id, sp_raw in raw.items()
                if sp_raw[m] is not None
            ]
            ranked_list = sorted(vals_list, key=lambda x: x[1])  # type: ignore[arg-type]
            n = len(ranked_list)
            for i, (sp_id, _) in enumerate(ranked_list):
                normed.setdefault(sp_id, {})[m] = (i + 1) / n

        scores = {
            sp_id: sum(normed.get(sp_id, {}).get(m, 0.0) * w for m, w in weights.items())
            for sp_id in fund_price_series
        }
        ranked_funds = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        n_funds = len(ranked_funds)

        def _status(rank: int) -> str:
            pct = rank / n_funds
            if pct <= 0.25:
                return "Strong"
            if pct <= 0.50:
                return "Good"
            if pct <= 0.75:
                return "Neutral"
            return "Watch"

        for rank, (sp_id, score) in enumerate(ranked_funds, 1):
            rr = RankingResult(
                ranking_run_id=ranking_run_id,
                scheme_plan_id=sp_id,
                rank=rank,
                score=round(score * 100, 2),
                prev_rank=rank + random.randint(-1, 2),
                rank_change=random.randint(-2, 2),
                status_label=_status(rank),
            )
            db.add(rr)
            db.flush()

            for m, w in weights.items():
                db.add(RankingComponentContribution(
                    ranking_result_id=rr.id,
                    metric_id=m,
                    raw_value=raw[sp_id].get(m),
                    normalized_value=normed.get(sp_id, {}).get(m),
                    weight=w,
                    contribution=normed.get(sp_id, {}).get(m, 0.0) * w,
                ))
        db.flush()
    print(f"  ✓ ranking_run + ranking_results ({len(cfg['funds'])} funds ranked)")


# ── Main ─────────────────────────────────────────────────────────────────────


def run(db: Session) -> None:
    print("Seeding AltStreet development database…")

    # ── Data version ──────────────────────────────────────────────────────────
    dv = db.get(DataVersion, 1)
    if dv is None:
        dv = DataVersion(
            id=1,
            as_of_date=EVAL_DATE,
            status=DataVersionStatus.PRODUCTION,
            notes="Seed data — synthetic NAVs",
        )
        db.add(dv)
        db.flush()
    print("  ✓ data_version")

    # ── Trading calendar ──────────────────────────────────────────────────────
    td_dates = trading_days(START_DATE, END_DATE)
    existing_tc = {r[0] for r in db.execute(text("SELECT date FROM trading_calendar")).fetchall()}
    new_tc = [
        TradingCalendar(date=d, is_trading_day=True)
        for d in td_dates if d not in existing_tc
    ]
    if new_tc:
        db.bulk_save_objects(new_tc)
        db.flush()
    print(f"  ✓ trading_calendar ({len(td_dates)} rows)")

    # ── Metric definitions ────────────────────────────────────────────────────
    metrics = [
        MetricDefinition(id="IR_1Y", name="1Y Information Ratio",
                         direction="higher_better", window_years=1,
                         formula_description="AER_1Y / TE_1Y"),
        MetricDefinition(id="IR_3Y", name="3Y Information Ratio",
                         direction="higher_better", window_years=3,
                         formula_description="AER_3Y / TE_3Y"),
        MetricDefinition(id="IR_SLOPE_2Y", name="2Y IR Slope",
                         direction="higher_better", window_years=2,
                         formula_description="OLS slope of monthly 3Y IR series"),
        MetricDefinition(id="IMPROVEMENT_METRIC", name="Improvement Metric",
                         direction="higher_better",
                         formula_description="avg(recent 12 IR) - avg(prior 12 IR)"),
        MetricDefinition(id="OUTPERFORMANCE_RATIO", name="Outperformance Ratio",
                         direction="higher_better",
                         formula_description="% of 3Y rolling IR > 0"),
    ]
    for m in metrics:
        if db.get(MetricDefinition, m.id) is None:
            db.add(m)
    db.flush()
    print("  ✓ metric definitions")

    # ── Rolling eval months (shared across all categories) ────────────────────
    eval_months: list[date] = []
    d = date(EVAL_DATE.year - 3, EVAL_DATE.month, 1)
    while d <= EVAL_DATE:
        last = date(d.year, d.month, 28)
        while last.weekday() >= 5:
            last -= timedelta(days=1)
        if last >= START_DATE:
            eval_months.append(last)
        if d.month == 12:
            d = date(d.year + 1, 1, 1)
        else:
            d = date(d.year, d.month + 1, 1)

    # ── Seed all three categories ─────────────────────────────────────────────
    for cfg in CATEGORY_CONFIGS:
        seed_category(db, cfg, dv, td_dates, eval_months)

    db.commit()
    print("\n✅ Seed complete — Large Cap, Mid Cap, and Small Cap are ready.")


if __name__ == "__main__":
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as session:
        run(session)
