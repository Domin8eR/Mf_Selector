"""Pure metric calculation functions (v9 specification).

All functions:
  - Are side-effect-free (no DB / IO).
  - Accept and return pandas Series / scalars.
  - Return None (not NaN) when a result cannot be computed.
  - Are covered by unit tests in tests/quant/test_metrics.py.

AI agents must NEVER call these functions directly — they call backend
APIs that return pre-computed values stored in metric_value_snapshot /
rolling_metric_value.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd
from scipy import stats

# ── Constants ────────────────────────────────────────────────────────────────

ANNUALISE: int = 252          # trading-day annualisation base
MIN_OBS: int = 63             # ~3 months minimum for any rolling metric
MIN_SLOPE_POINTS: int = 4     # minimum monthly points for OLS slope


# ── Return calculations ──────────────────────────────────────────────────────

def daily_returns(prices: pd.Series) -> pd.Series:
    """r_t = price_t / price_{t-1} − 1.  First element is dropped."""
    return prices.pct_change().dropna()


def annualised_return(prices: pd.Series) -> float | None:
    """
    Geometric annualised return over the full price window.
    n = number of return observations (len(prices) − 1).
    """
    n = len(prices) - 1
    if n < 1:
        return None
    start, end = float(prices.iloc[0]), float(prices.iloc[-1])
    if start <= 0 or end <= 0:
        return None
    return float((end / start) ** (ANNUALISE / n) - 1)


def cagr_from_total_return(total_return_fraction: float | None, years: float) -> float | None:
    """
    Annualised (CAGR) % from a known total-return fraction over a known
    calendar-year span — e.g. total_return_fraction=0.26, years=3 -> ~8.0%.

    Calendar-year based, not trading-day-count based, so unlike
    annualised_return() above it doesn't need a daily price series — just
    the total return and real elapsed time. Correct for a downsampled or
    sparse point series (e.g. a chart with ~150 sampled points over several
    years) where treating point-count as a trading-day count would badly
    overstate the annualisation.

    Extracted from two identical inline copies (app/routers/metrics.py's
    bm_cagr, app/ai/tools.py's _bm_cagr) — one calculation, not two kept in
    sync by hand.
    """
    if total_return_fraction is None or years <= 0:
        return None
    return round(((1 + total_return_fraction) ** (1 / years) - 1) * 100, 2)


def excess_returns(
    fund_returns: pd.Series,
    benchmark_returns: pd.Series,
) -> pd.Series:
    """
    Align fund and benchmark return series on date index then compute
    e_t = r_f,t − r_b,t.  Only dates present in both series are kept.
    """
    aligned = pd.concat([fund_returns, benchmark_returns], axis=1).dropna()
    aligned.columns = ["f", "b"]
    return aligned["f"] - aligned["b"]


def tracking_error(excess_ret: pd.Series) -> float | None:
    """TE = std(e_t, ddof=1) × √252.  Returns None if < 4 observations."""
    if len(excess_ret) < 4:
        return None
    te = float(excess_ret.std(ddof=1) * (ANNUALISE ** 0.5))
    return te if te > 0 else None


# ── Information Ratio ────────────────────────────────────────────────────────

@dataclass
class IRResult:
    value: float | None
    annualised_excess_return: float | None
    tracking_error_value: float | None
    observation_count: int
    window_start_date: date | None
    window_end_date: date | None
    status: str          # "ok" | "insufficient_data" | "zero_tracking_error"
    confidence: str      # "high" | "medium" | "low"


def information_ratio(
    fund_prices: pd.Series,
    benchmark_prices: pd.Series,
    min_obs: int = MIN_OBS,
) -> IRResult:
    """
    Information Ratio = Annualised Excess Return / Tracking Error.

    Prices must be indexed by date.  Only dates where BOTH series have
    valid (non-NaN, positive) prices are used.
    """
    fund_ret = daily_returns(fund_prices)
    bm_ret = daily_returns(benchmark_prices)

    # Align on common dates
    combined = pd.concat([fund_ret, bm_ret], axis=1).dropna()
    combined.columns = ["f", "b"]
    n = len(combined)

    start_date = combined.index[0] if n > 0 else None
    end_date = combined.index[-1] if n > 0 else None

    if n < min_obs:
        return IRResult(
            value=None, annualised_excess_return=None,
            tracking_error_value=None, observation_count=n,
            window_start_date=start_date, window_end_date=end_date,
            status="insufficient_data", confidence="low",
        )

    exc = combined["f"] - combined["b"]

    # Annualised returns using the aligned window endpoints
    f_window = fund_prices.loc[combined.index[0]:combined.index[-1]]
    b_window = benchmark_prices.loc[combined.index[0]:combined.index[-1]]
    ar_f = annualised_return(f_window)
    ar_b = annualised_return(b_window)

    if ar_f is None or ar_b is None:
        return IRResult(
            value=None, annualised_excess_return=None,
            tracking_error_value=None, observation_count=n,
            window_start_date=start_date, window_end_date=end_date,
            status="insufficient_data", confidence="low",
        )

    aer = ar_f - ar_b
    te = tracking_error(exc)

    if te is None:
        return IRResult(
            value=None, annualised_excess_return=aer,
            tracking_error_value=None, observation_count=n,
            window_start_date=start_date, window_end_date=end_date,
            status="zero_tracking_error", confidence="low",
        )

    ir = aer / te
    confidence = "high" if n >= ANNUALISE else ("medium" if n >= MIN_OBS * 2 else "low")

    return IRResult(
        value=float(ir), annualised_excess_return=float(aer),
        tracking_error_value=float(te), observation_count=n,
        window_start_date=start_date, window_end_date=end_date,
        status="ok", confidence=confidence,
    )


# ── IR Slope ─────────────────────────────────────────────────────────────────

@dataclass
class SlopeResult:
    value: float | None
    r_squared: float | None
    observation_count: int
    status: str


def ir_slope(
    rolling_ir_series: pd.Series,
    min_points: int = MIN_SLOPE_POINTS,
) -> SlopeResult:
    """
    OLS slope of a monthly rolling IR series.

    t_i = 0, 1, 2, … (month index).
    Positive slope → IR improving over time.
    """
    valid = rolling_ir_series.dropna()
    n = len(valid)

    if n < min_points:
        return SlopeResult(value=None, r_squared=None,
                           observation_count=n, status="insufficient_data")

    t = np.arange(n, dtype=float)
    result = stats.linregress(t, valid.values.astype(float))

    return SlopeResult(
        value=float(result.slope),
        r_squared=float(result.rvalue ** 2),
        observation_count=n,
        status="ok",
    )


# ── Improvement metric ───────────────────────────────────────────────────────

def improvement_metric(
    rolling_ir_series: pd.Series,
    recent_n: int = 12,
    prior_n: int = 12,
) -> float | None:
    """
    avg(most recent `recent_n` observations) − avg(prior `prior_n` observations).
    Returns None if there are not enough valid observations.
    """
    valid = rolling_ir_series.dropna()
    if len(valid) < recent_n + 1:
        return None

    recent = float(valid.iloc[-recent_n:].mean())
    prior_slice = valid.iloc[-(recent_n + prior_n):-recent_n]
    if len(prior_slice) < 1:
        return None

    return recent - float(prior_slice.mean())


# ── Outperformance ratio ─────────────────────────────────────────────────────

def outperformance_ratio(rolling_ir_series: pd.Series) -> float | None:
    """% of non-null rolling IR observations that are > 0."""
    valid = rolling_ir_series.dropna()
    if len(valid) < 1:
        return None
    return float((valid > 0).sum() / len(valid))


# ── Drawdown ─────────────────────────────────────────────────────────────────

def max_drawdown(prices: pd.Series) -> float | None:
    """Maximum peak-to-trough drawdown over the full price series."""
    if len(prices) < 2:
        return None
    rolling_peak = prices.cummax()
    drawdown = prices / rolling_peak - 1
    return float(drawdown.min())


# ── Downside capture ratio ───────────────────────────────────────────────────

def downside_capture_ratio(
    fund_returns: pd.Series,
    benchmark_returns: pd.Series,
) -> float | None:
    """Downside capture ratio as a percentage.

    Among periods where the benchmark return is negative, compares the
    geometric mean of the fund's returns to the geometric mean of the
    benchmark's returns.  A ratio < 100 means the fund loses less than
    the benchmark in down markets (favourable).

    Returns None when there are fewer than 2 down-market periods or when
    the two series have no overlapping index values.

    Note: the navhist table currently only holds 9 days of data; this
    function is unit-tested against synthetic series but cannot be applied
    to real funds until daily price history is fully imported.
    """
    aligned = fund_returns.align(benchmark_returns, join="inner")
    f_ret, b_ret = aligned

    mask = b_ret < 0
    if mask.sum() < 2:
        return None

    f_down = f_ret[mask]
    b_down = b_ret[mask]
    n = mask.sum()

    bm_geo = float((1 + b_down).prod() ** (1 / n) - 1)
    if bm_geo == 0:
        return None

    fund_geo = float((1 + f_down).prod() ** (1 / n) - 1)
    return round((fund_geo / bm_geo) * 100, 4)


# ── Normalisation helpers ────────────────────────────────────────────────────

def percentile_rank(
    value: float,
    universe: list[float],
    direction: str = "higher_better",
) -> float:
    """
    Cross-sectional percentile rank scaled to [0, 1].
    direction = "higher_better"  →  higher value → higher rank (closer to 1)
    direction = "lower_better"   →  lower value  → higher rank (closer to 1)
    """
    if not universe:
        return 0.0
    n = len(universe)
    rank = sum(1 for v in universe if v <= value)
    pct = rank / n
    return pct if direction == "higher_better" else 1.0 - pct


# ── Active Share ──────────────────────────────────────────────────────────────

def active_share(
    fund_weights: dict[str, float],
    benchmark_weights: dict[str, float],
) -> dict:
    """
    Active Share = 0.5 * sum(|w_fund_i - w_bm_i|) across union of all securities.
    Weights should be in percent (0-100). Returns value in percent.
    Returns {"value": float, "status": "ok"} or {"value": None, "status": "insufficient_data"}.
    """
    if not fund_weights or not benchmark_weights:
        return {"value": None, "status": "insufficient_data"}
    all_securities = set(fund_weights.keys()) | set(benchmark_weights.keys())
    if not all_securities:
        return {"value": None, "status": "insufficient_data"}
    total = sum(abs(fund_weights.get(s, 0.0) - benchmark_weights.get(s, 0.0)) for s in all_securities)
    return {"value": round(total * 0.5, 4), "status": "ok"}


# ── Portfolio Stability ───────────────────────────────────────────────────────

def portfolio_stability(
    current_weights: dict[str, float],
    historical_weights: dict[str, float],
) -> dict:
    """
    Portfolio Stability = weighted_overlap between current and historical holdings.
    weighted_overlap = sum(min(w_current_i, w_historical_i)) across all common securities.
    Higher = more stable (lower turnover). Returns value in percent (0-100).
    Returns {"value": float, "status": "ok"} or {"value": None, "status": "insufficient_data"}.
    """
    if not current_weights or not historical_weights:
        return {"value": None, "status": "insufficient_data"}
    common = set(current_weights.keys()) & set(historical_weights.keys())
    if not common:
        return {"value": 0.0, "status": "ok"}
    overlap = sum(min(current_weights[s], historical_weights[s]) for s in common)
    return {"value": round(overlap, 4), "status": "ok"}
