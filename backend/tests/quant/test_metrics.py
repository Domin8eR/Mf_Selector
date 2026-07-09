"""Unit tests for app.quant.metrics.

Every test uses hand-calculated or analytically known values so that
regressions are immediately obvious.  No DB, no IO.
"""

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from app.quant.metrics import (
    ANNUALISE,
    IRResult,
    annualised_return,
    daily_returns,
    downside_capture_ratio,
    excess_returns,
    improvement_metric,
    information_ratio,
    ir_slope,
    max_drawdown,
    outperformance_ratio,
    percentile_rank,
    tracking_error,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _dates(n: int, start: date = date(2021, 1, 4)) -> list[date]:
    """Generate n consecutive weekday dates."""
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _prices(values: list[float], start: date = date(2021, 1, 4)) -> pd.Series:
    dates = _dates(len(values), start)
    return pd.Series(values, index=dates, dtype=float)


def _flat_growth(start: float, annual_rate: float, n: int) -> pd.Series:
    """n+1 prices growing geometrically at annual_rate over n trading days."""
    daily = (1 + annual_rate) ** (1 / ANNUALISE)
    values = [start * daily ** i for i in range(n + 1)]
    return _prices(values)


# ── daily_returns ─────────────────────────────────────────────────────────────

def test_daily_returns_length() -> None:
    p = _prices([100.0, 101.0, 102.0])
    r = daily_returns(p)
    assert len(r) == 2


def test_daily_returns_values() -> None:
    p = _prices([100.0, 110.0, 99.0])
    r = daily_returns(p)
    assert abs(r.iloc[0] - 0.10) < 1e-10
    assert abs(r.iloc[1] - (-0.10)) < 1e-9


def test_daily_returns_empty() -> None:
    p = _prices([100.0])
    r = daily_returns(p)
    assert len(r) == 0


# ── annualised_return ─────────────────────────────────────────────────────────

def test_annualised_return_flat() -> None:
    # 252 observations of 10% annual growth → should return exactly 10%
    prices = _flat_growth(100.0, 0.10, 252)
    ar = annualised_return(prices)
    assert ar is not None
    assert abs(ar - 0.10) < 1e-9


def test_annualised_return_zero_growth() -> None:
    prices = _prices([100.0] * 253)
    ar = annualised_return(prices)
    assert ar is not None
    assert abs(ar) < 1e-9


def test_annualised_return_single_price() -> None:
    assert annualised_return(_prices([100.0])) is None


def test_annualised_return_negative_start() -> None:
    assert annualised_return(_prices([0.0, 100.0])) is None


# ── tracking_error ────────────────────────────────────────────────────────────

def test_tracking_error_constant_excess() -> None:
    # Constant excess return → std = 0 → TE = 0 → None
    exc = pd.Series([0.001] * 252)
    assert tracking_error(exc) is None


def test_tracking_error_insufficient() -> None:
    exc = pd.Series([0.001, 0.002, 0.003])  # < 4 obs
    assert tracking_error(exc) is None


def test_tracking_error_known_value() -> None:
    # Daily excess std of exactly 0.01 → TE = 0.01 * √252
    rng = np.random.default_rng(42)
    exc = pd.Series(rng.normal(0.0, 0.01, 500))
    te = tracking_error(exc)
    assert te is not None
    expected = 0.01 * math.sqrt(ANNUALISE)
    assert abs(te - expected) < 0.005  # within 0.5% of theoretical


# ── information_ratio ────────────────────────────────────────────────────────

def test_ir_positive_when_fund_beats_benchmark() -> None:
    fund = _flat_growth(100.0, 0.14, 252)
    bm = _flat_growth(100.0, 0.08, 252)
    result = information_ratio(fund, bm)
    assert result.status == "ok"
    assert result.value is not None
    assert result.value > 0


def test_ir_negative_when_fund_underperforms() -> None:
    fund = _flat_growth(100.0, 0.05, 252)
    bm = _flat_growth(100.0, 0.12, 252)
    result = information_ratio(fund, bm)
    assert result.status == "ok"
    assert result.value is not None
    assert result.value < 0


def test_ir_insufficient_data() -> None:
    fund = _flat_growth(100.0, 0.10, 30)  # only 30 observations
    bm = _flat_growth(100.0, 0.08, 30)
    result = information_ratio(fund, bm)
    assert result.status == "insufficient_data"
    assert result.value is None


def test_ir_identical_fund_and_benchmark_returns_none() -> None:
    prices = _flat_growth(100.0, 0.10, 252)
    result = information_ratio(prices, prices)
    # Identical series → all excess returns = 0 → TE = 0 → None
    assert result.value is None
    assert result.status in ("zero_tracking_error", "insufficient_data")


def test_ir_observation_count() -> None:
    fund = _flat_growth(100.0, 0.12, 300)
    bm = _flat_growth(100.0, 0.08, 300)
    result = information_ratio(fund, bm)
    assert result.observation_count == 300


# ── ir_slope ─────────────────────────────────────────────────────────────────

def test_slope_positive_improving_series() -> None:
    # IR values that strictly increase → positive slope
    s = pd.Series([0.1, 0.2, 0.3, 0.4, 0.5, 0.6])
    res = ir_slope(s)
    assert res.status == "ok"
    assert res.value is not None
    assert res.value > 0


def test_slope_negative_declining_series() -> None:
    s = pd.Series([0.6, 0.5, 0.4, 0.3, 0.2, 0.1])
    res = ir_slope(s)
    assert res.status == "ok"
    assert res.value is not None
    assert res.value < 0


def test_slope_insufficient_data() -> None:
    s = pd.Series([0.1, 0.2, 0.3])  # < MIN_SLOPE_POINTS=4
    res = ir_slope(s)
    assert res.status == "insufficient_data"
    assert res.value is None


def test_slope_ignores_nans() -> None:
    s = pd.Series([float("nan"), 0.2, 0.3, 0.4, 0.5])
    res = ir_slope(s)
    assert res.status == "ok"
    assert res.observation_count == 4


def test_slope_known_value() -> None:
    # Perfect linear series 0, 0.1, 0.2, 0.3 → slope = 0.1
    s = pd.Series([0.0, 0.1, 0.2, 0.3])
    res = ir_slope(s)
    assert res.value is not None
    assert abs(res.value - 0.1) < 1e-9


# ── improvement_metric ───────────────────────────────────────────────────────

def test_improvement_metric_positive() -> None:
    # Recent 12 avg = 0.5, prior 12 avg = 0.1 → improvement = 0.4
    values = [0.1] * 12 + [0.5] * 12
    s = pd.Series(values)
    im = improvement_metric(s, recent_n=12, prior_n=12)
    assert im is not None
    assert abs(im - 0.4) < 1e-9


def test_improvement_metric_negative() -> None:
    values = [0.5] * 12 + [0.1] * 12
    s = pd.Series(values)
    im = improvement_metric(s, recent_n=12, prior_n=12)
    assert im is not None
    assert im < 0


def test_improvement_metric_insufficient_data() -> None:
    s = pd.Series([0.1, 0.2, 0.3])  # fewer than recent_n+1 points
    assert improvement_metric(s, recent_n=12, prior_n=12) is None


# ── outperformance_ratio ─────────────────────────────────────────────────────

def test_outperformance_ratio_all_positive() -> None:
    s = pd.Series([0.1, 0.5, 0.8, 1.2])
    assert outperformance_ratio(s) == 1.0


def test_outperformance_ratio_all_negative() -> None:
    s = pd.Series([-0.1, -0.5])
    assert outperformance_ratio(s) == 0.0


def test_outperformance_ratio_mixed() -> None:
    s = pd.Series([0.1, -0.2, 0.3, -0.4])
    opr = outperformance_ratio(s)
    assert opr is not None
    assert abs(opr - 0.5) < 1e-9


def test_outperformance_ratio_empty() -> None:
    assert outperformance_ratio(pd.Series([], dtype=float)) is None


# ── max_drawdown ──────────────────────────────────────────────────────────────

def test_max_drawdown_known_value() -> None:
    # Peak = 100 at index 0, trough = 80 at index 2 → DD = -20%
    prices = _prices([100.0, 90.0, 80.0, 85.0])
    dd = max_drawdown(prices)
    assert dd is not None
    assert abs(dd - (-0.20)) < 1e-9


def test_max_drawdown_no_drawdown() -> None:
    prices = _prices([100.0, 110.0, 120.0])
    dd = max_drawdown(prices)
    assert dd is not None
    assert abs(dd) < 1e-9  # no drawdown = 0


def test_max_drawdown_single_price() -> None:
    assert max_drawdown(_prices([100.0])) is None


# ── percentile_rank ───────────────────────────────────────────────────────────

def test_percentile_rank_higher_better() -> None:
    universe = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert percentile_rank(5.0, universe, "higher_better") == 1.0
    assert percentile_rank(1.0, universe, "higher_better") == 0.2


def test_percentile_rank_lower_better() -> None:
    universe = [1.0, 2.0, 3.0, 4.0, 5.0]
    # value=1.0 has percentile 0.2 higher_better → 0.8 lower_better
    assert abs(percentile_rank(1.0, universe, "lower_better") - 0.8) < 1e-9


def test_percentile_rank_empty_universe() -> None:
    assert percentile_rank(1.0, [], "higher_better") == 0.0


# ── downside_capture_ratio ────────────────────────────────────────────────────

def _returns(values: list[float], start: date = date(2021, 1, 4)) -> pd.Series:
    """Build a returns Series from a list of decimal returns."""
    dates = _dates(len(values), start)
    return pd.Series(values, index=dates, dtype=float)


def test_downside_capture_ratio_fund_captures_less() -> None:
    """Fund loses 50% as much as benchmark in down periods → ratio ≈ 50."""
    bm = _returns([-0.02, 0.01, -0.03, 0.02, -0.04, 0.01])
    # Fund loses exactly half of benchmark on each down day
    fund = _returns([-0.01, 0.01, -0.015, 0.02, -0.02, 0.01])
    ratio = downside_capture_ratio(fund, bm)
    assert ratio is not None
    # Geometric mean of [-0.01, -0.015, -0.02] / geometric mean of [-0.02, -0.03, -0.04]
    # ≈ 50% capture — allow ±2% tolerance for geometric rounding
    assert 48 < ratio < 52, f"Expected ~50, got {ratio}"


def test_downside_capture_ratio_fund_loses_more() -> None:
    """Fund loses 200% of benchmark in down periods → ratio > 100."""
    bm   = _returns([-0.02, 0.01, -0.03, 0.02])
    fund = _returns([-0.04, 0.01, -0.06, 0.02])
    ratio = downside_capture_ratio(fund, bm)
    assert ratio is not None
    assert ratio > 100


def test_downside_capture_ratio_no_down_periods() -> None:
    """When benchmark never goes negative, result is None."""
    bm   = _returns([0.01, 0.02, 0.03])
    fund = _returns([0.01, 0.02, 0.03])
    assert downside_capture_ratio(fund, bm) is None


def test_downside_capture_ratio_only_one_down_period() -> None:
    """Fewer than 2 down periods → None (not statistically meaningful)."""
    bm   = _returns([-0.02, 0.01, 0.02, 0.03])
    fund = _returns([-0.01, 0.01, 0.02, 0.03])
    assert downside_capture_ratio(fund, bm) is None


def test_downside_capture_ratio_misaligned_index() -> None:
    """Non-overlapping indices → None (align produces empty intersection)."""
    d1 = date(2021, 1, 4)
    d2 = date(2022, 1, 3)
    bm   = _returns([-0.02, -0.03, -0.04], start=d1)
    fund = _returns([-0.01, -0.015, -0.02], start=d2)
    # After alignment the intersection is empty (different dates)
    assert downside_capture_ratio(fund, bm) is None
