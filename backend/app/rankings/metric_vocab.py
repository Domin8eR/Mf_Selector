"""
The vetted metric vocabulary — every metric_column a rule component is
allowed to reference, with the real table it lives in and its percentile
direction.

Shared by app/routers/rules.py (Rule Playground sandbox preview + component
validation) and app/rankings/recompute.py (the governed recompute engine),
so there is exactly one allowlist, not two that could drift apart. Also
guards recompute.py's dynamic SQL: a component's metric_source/metric_column
is only ever interpolated into a query after being checked against this
dict, never trusted as free-form input.
"""

METRIC_VOCAB: dict[str, dict] = {
    "information_ratio_3yr": {
        "label": "IR₃ (3Y Information Ratio)",
        "source": "selfmade_scheme_metrics",
        "direction": "higher_better",
        "window_months": 36,
        "short_window": False,
    },
    "sharpe_ratio_3yr": {
        "label": "Sharpe₃ (3Y Sharpe Ratio)",
        "source": "selfmade_scheme_metrics",
        "direction": "higher_better",
        "window_months": 36,
        "short_window": False,
    },
    "tracking_error_3yr": {
        "label": "TE₃ (3Y Tracking Error)",
        "source": "selfmade_scheme_metrics",
        "direction": "lower_better",
        "window_months": 36,
        "short_window": False,
    },
    "ir_slope_6m_proxy": {
        "label": "IR Slope (6m proxy)",
        "source": "selfmade_scheme_metrics",
        "direction": "higher_better",
        "window_months": 6,
        "short_window": True,
    },
    "jensens_alpha_3yr": {
        "label": "Alpha₃ (3Y Jensen's Alpha)",
        "source": "selfmade_scheme_metrics",
        "direction": "higher_better",
        "window_months": 36,
        "short_window": False,
    },
    "fund_1yr_ret": {
        "label": "1Y Fund Return",
        "source": "selfmade_scheme_returns",
        "direction": "higher_better",
        "window_months": 12,
        "short_window": True,
    },
    "fund_3yr_ret": {
        "label": "3Y Fund Return (CAGR)",
        "source": "selfmade_scheme_returns",
        "direction": "higher_better",
        "window_months": 36,
        "short_window": False,
    },
    "fund_5yr_ret": {
        "label": "5Y Fund Return (CAGR)",
        "source": "selfmade_scheme_returns",
        "direction": "higher_better",
        "window_months": 60,
        "short_window": False,
    },
    "active_1yr_ret": {
        "label": "1Y Active Return",
        "source": "selfmade_scheme_returns",
        "direction": "higher_better",
        "window_months": 12,
        "short_window": True,
    },
    "active_3yr_ret": {
        "label": "3Y Active Return (CAGR)",
        "source": "selfmade_scheme_returns",
        "direction": "higher_better",
        "window_months": 36,
        "short_window": False,
    },
    "active_5yr_ret": {
        "label": "5Y Active Return (CAGR)",
        "source": "selfmade_scheme_returns",
        "direction": "higher_better",
        "window_months": 60,
        "short_window": False,
    },
    "expense_ratio_pct": {
        "label": "Expense Ratio %",
        "source": "selfmade_expense_ratio",
        "direction": "lower_better",
        "window_months": None,
        "short_window": False,
    },
    "rank_delta_6m": {
        "label": "Rank Change (6m)",
        "source": "selfmade_ranking_snapshot",
        "direction": "lower_better",
        "window_months": 6,
        "short_window": True,
    },
}

_ALL_METRIC_COLS = list(METRIC_VOCAB.keys())
