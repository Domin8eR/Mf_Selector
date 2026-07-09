"""
Deterministic insight generation for the Rule Playground.

Reads the current sandbox editor state and (optionally) a sandbox run result,
and emits the appropriate RULE_*_V1 insight cards.

Language rule: NEVER use "recommendation", "buy", "sell", "best fund", "top pick".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.insights.renderer import render_insight_template

# ── Short-window metric classification ───────────────────────────────────────

_SHORT_WINDOW_METRICS: set[str] = {
    "ir_slope_6m_proxy",
    "active_1yr_ret",
    "fund_1yr_ret",
    "rank_delta_6m",
}

_RETURN_METRICS: set[str] = {
    "fund_1yr_ret", "fund_3yr_ret", "fund_5yr_ret",
    "active_1yr_ret", "active_3yr_ret", "active_5yr_ret",
}

_RISK_ADJ_METRICS: set[str] = {
    "information_ratio_3yr", "sharpe_ratio_3yr", "jensens_alpha_3yr",
    "sortino_ratio_3yr",
}

WEIGHT_EPSILON = 0.005  # 0.5 percentage-point tolerance


# ── Input dataclasses ─────────────────────────────────────────────────────────

@dataclass
class SandboxComponent:
    metric_column: str
    weight_pct: float          # 0–100
    formula_text: str | None = None


@dataclass
class FormulaValidationStatus:
    component_name: str
    valid: bool
    error_type: str | None = None
    error_message: str | None = None
    parsed_variables: list[str] = field(default_factory=list)
    sample_result: float | None = None


@dataclass
class SandboxRunSummary:
    fund_count: int
    promoted: int
    dropped: int
    no_change: int
    top10_turnover_pct: float
    entering_funds: list[str]
    leaving_funds: list[str]
    beneficiary_name: str
    beneficiary_default_rank: int
    beneficiary_sandbox_rank: int
    beneficiary_places: int
    loser_name: str
    loser_default_rank: int
    loser_sandbox_rank: int
    loser_places: int
    category_shifts: dict[str, float] | None = None


@dataclass
class SandboxState:
    components: list[SandboxComponent]
    formula_validations: list[FormulaValidationStatus]
    sandbox_run: SandboxRunSummary | None
    rationale_present: bool
    category: str


# ── Main generator ────────────────────────────────────────────────────────────

def generate_rule_playground_insights(state: SandboxState) -> list[dict[str, Any]]:
    """
    Evaluate all RULE_*_V1 conditions against the current sandbox state and
    return a list of rendered insight cards (dicts).

    All logic is deterministic — no LLM calls.
    """
    cards: list[dict[str, Any]] = []

    # ── Weight validation ─────────────────────────────────────────────────────
    total_pct   = sum(c.weight_pct for c in state.components)
    n_comp      = len(state.components)
    negative    = [c for c in state.components if c.weight_pct < 0]

    if negative:
        c = negative[0]
        card = render_insight_template("RULE_WEIGHTS_INVALID_NEGATIVE_V1", {
            "offending_component": c.metric_column,
            "offending_weight":    c.weight_pct,
        })
    elif abs(total_pct - 100.0) <= WEIGHT_EPSILON * 100:
        card = render_insight_template("RULE_WEIGHTS_VALID_V1", {
            "total_pct":       total_pct,
            "component_count": n_comp,
        })
    elif total_pct > 100.0 + WEIGHT_EPSILON * 100:
        card = render_insight_template("RULE_WEIGHTS_INVALID_TOTAL_HIGH_V1", {
            "total_pct":       total_pct,
            "component_count": n_comp,
            "excess_pct":      total_pct - 100.0,
        })
    else:
        card = render_insight_template("RULE_WEIGHTS_INVALID_TOTAL_LOW_V1", {
            "total_pct":       total_pct,
            "component_count": n_comp,
            "shortfall_pct":   100.0 - total_pct,
        })

    if card:
        cards.append(card.model_dump())

    weights_valid = (
        not negative
        and abs(total_pct - 100.0) <= WEIGHT_EPSILON * 100
    )

    # ── Formula validation ────────────────────────────────────────────────────
    formulas_valid = True
    for fv in state.formula_validations:
        if fv.valid:
            sr_text = f"{fv.sample_result:.4f}" if fv.sample_result is not None else "n/a"
            card = render_insight_template("RULE_FORMULA_VALID_V1", {
                "formula_component": fv.component_name,
                "parsed_variables":  ", ".join(fv.parsed_variables) or "none",
                "sample_result":     sr_text,
            })
        elif fv.error_type == "syntax":
            formulas_valid = False
            card = render_insight_template("RULE_FORMULA_INVALID_SYNTAX_V1", {
                "formula_component": fv.component_name,
                "parse_error":       fv.error_message or "unknown error",
            })
        elif fv.error_type == "invalid_variable":
            formulas_valid = False
            card = render_insight_template("RULE_FORMULA_INVALID_VARIABLE_V1", {
                "formula_component": fv.component_name,
                "unknown_variables": fv.error_message or "unknown",
                "available_sample":  "information_ratio_3yr, sharpe_ratio_3yr, …",
            })
        elif fv.error_type in ("invalid_function", "disallowed_construct"):
            formulas_valid = False
            card = render_insight_template("RULE_FORMULA_INVALID_FUNCTION_V1", {
                "formula_component":  fv.component_name,
                "unsupported_functions": fv.error_message or "unknown function",
            })
        else:
            formulas_valid = False
            card = None

        if card:
            cards.append(card.model_dump())

    # ── Recency bias ──────────────────────────────────────────────────────────
    short_components = [c for c in state.components if c.metric_column in _SHORT_WINDOW_METRICS]
    short_pct = sum(c.weight_pct for c in short_components)
    short_names = ", ".join(c.metric_column for c in short_components) or "none"

    if short_pct > 50.0:
        card = render_insight_template("RULE_RECENCY_BIAS_WARNING_V1", {
            "short_window_pct":        short_pct,
            "short_window_components": short_names,
        })
    else:
        card = render_insight_template("RULE_RECENCY_BIAS_OK_V1", {
            "short_window_pct": short_pct,
        })
    if card:
        cards.append(card.model_dump())

    # ── Return-heavy / balanced ───────────────────────────────────────────────
    return_pct   = sum(c.weight_pct for c in state.components if c.metric_column in _RETURN_METRICS)
    risk_adj_pct = sum(c.weight_pct for c in state.components if c.metric_column in _RISK_ADJ_METRICS)

    if return_pct > 50.0 and risk_adj_pct < 30.0:
        card = render_insight_template("RULE_RETURN_HEAVY_WARNING_V1", {
            "return_pct":    return_pct,
            "risk_adj_pct":  risk_adj_pct,
        })
    else:
        card = render_insight_template("RULE_RETURN_BALANCED_V1", {
            "return_pct":   return_pct,
            "risk_adj_pct": risk_adj_pct,
        })
    if card:
        cards.append(card.model_dump())

    # ── Sandbox-dependent insights ────────────────────────────────────────────
    run = state.sandbox_run
    if run:
        # Churn
        if run.top10_turnover_pct > 40.0:
            card = render_insight_template("RULE_HIGH_CHURN_WARNING_V1", {
                "turnover_pct":  run.top10_turnover_pct,
                "entering_funds": ", ".join(run.entering_funds[:5]) or "none",
                "leaving_funds":  ", ".join(run.leaving_funds[:5]) or "none",
            })
        else:
            card = render_insight_template("RULE_CHURN_NORMAL_V1", {
                "turnover_pct": run.top10_turnover_pct,
            })
        if card:
            cards.append(card.model_dump())

        # Category bias
        if run.category_shifts and len(run.category_shifts) >= 2:
            shifts   = list(run.category_shifts.items())
            max_item = max(shifts, key=lambda x: x[1])
            min_item = min(shifts, key=lambda x: x[1])
            ratio    = (max_item[1] / max(min_item[1], 0.01)) if min_item[1] > 0 else 99.0
            if ratio >= 2.0:
                card = render_insight_template("RULE_CATEGORY_BIAS_WARNING_V1", {
                    "high_churn_category": max_item[0],
                    "max_shift":           max_item[1],
                    "low_churn_category":  min_item[0],
                    "min_shift":           min_item[1],
                })
            else:
                card = render_insight_template("RULE_CATEGORY_BIAS_NONE_V1", {
                    "shift_ratio": ratio,
                })
            if card:
                cards.append(card.model_dump())

        # Beneficiary / loser
        if run.beneficiary_places > 0:
            card = render_insight_template("RULE_TOP_SANDBOX_BENEFICIARY_V1", {
                "fund_name":    run.beneficiary_name,
                "places":       run.beneficiary_places,
                "default_rank": run.beneficiary_default_rank,
                "sandbox_rank": run.beneficiary_sandbox_rank,
            })
            if card:
                cards.append(card.model_dump())

        if run.loser_places > 0:
            card = render_insight_template("RULE_TOP_SANDBOX_LOSER_V1", {
                "fund_name":    run.loser_name,
                "places":       run.loser_places,
                "default_rank": run.loser_default_rank,
                "sandbox_rank": run.loser_sandbox_rank,
            })
            if card:
                cards.append(card.model_dump())

    # ── Approval readiness ────────────────────────────────────────────────────
    blocking: list[str] = []
    if not weights_valid:
        blocking.append("weights do not sum to 100%")
    if not formulas_valid:
        blocking.append("one or more formulas have errors")
    if not run:
        blocking.append("sandbox run has not been completed")
    if not state.rationale_present:
        blocking.append("rationale text is missing")

    has_high_severity = any(
        c.get("severity") == "warning" for c in cards
        if isinstance(c, dict)
    )

    if blocking or has_high_severity:
        if has_high_severity and "warnings present (churn or bias)" not in blocking:
            blocking.append("high-severity warnings present (churn or bias)")
        card = render_insight_template("RULE_NOT_READY_FOR_APPROVAL_V1", {
            "blocking_check_count": len(blocking),
            "blocking_checks":      "; ".join(blocking),
        })
    else:
        card = render_insight_template("RULE_READY_FOR_APPROVAL_V1", {
            "fund_count": run.fund_count if run else 0,
        })
    if card:
        cards.append(card.model_dump())

    return cards
