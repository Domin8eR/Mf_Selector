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
    Evaluate the current sandbox state and return 7 RULE_*_V1 compact insight
    cards (2026-07-18 migration — down from 20).

    Formula validation (RULE_FORMULA_*_V1) is dropped as a card — it already
    renders directly via the Formula Validation checklist UI. Category bias
    and top-sandbox-beneficiary/loser are dropped as cards too, but the
    calculations stay available on SandboxRunSummary for the results table's
    movement arrows to use directly, instead of a separate card.

    All logic is deterministic — no LLM calls.
    """
    import datetime as _dt
    cards: list[dict[str, Any]] = []
    eval_date_str = str(_dt.date.today())

    def _base(entity_id: str = "rule_playground") -> dict:
        return {"entity_id": entity_id, "evaluation_date": eval_date_str}

    # ── Weight validation ─────────────────────────────────────────────────────
    total_pct = sum(c.weight_pct for c in state.components)
    negative = [c for c in state.components if c.weight_pct < 0]
    weights_valid = not negative and abs(total_pct - 100.0) <= WEIGHT_EPSILON * 100

    if weights_valid:
        card = render_insight_template("RULE_WEIGHTS_VALID_V1", {
            **_base(), "total_weight_pct": round(total_pct, 1),
            "duplicate_metric_status": "none",
        })
    else:
        card = render_insight_template("RULE_WEIGHTS_INVALID_V1", {
            **_base(), "total_weight_pct": round(total_pct, 1),
            "weight_gap_pct": round(abs(100.0 - total_pct), 1),
        })
    if card:
        cards.append(card.model_dump())

    # ── Formula validation (not rendered as a card — checklist UI covers it) ──
    formulas_valid = all(
        fv.valid for fv in state.formula_validations
    ) if state.formula_validations else True

    # ── Recency bias ──────────────────────────────────────────────────────────
    short_pct = sum(c.weight_pct for c in state.components if c.metric_column in _SHORT_WINDOW_METRICS)
    if short_pct > 50.0:
        card = render_insight_template("RULE_RECENCY_BIAS_WARNING_V1", {
            **_base(), "short_window_weight_pct": round(short_pct, 1),
        })
        if card:
            cards.append(card.model_dump())

    # ── Return-heavy ──────────────────────────────────────────────────────────
    return_pct = sum(c.weight_pct for c in state.components if c.metric_column in _RETURN_METRICS)
    risk_adj_pct = sum(c.weight_pct for c in state.components if c.metric_column in _RISK_ADJ_METRICS)
    if return_pct > 50.0 and risk_adj_pct < 30.0:
        card = render_insight_template("RULE_RETURN_HEAVY_WARNING_V1", {
            **_base(), "absolute_return_weight_pct": round(return_pct, 1),
            "risk_adjusted_weight_pct": round(risk_adj_pct, 1),
        })
        if card:
            cards.append(card.model_dump())

    # ── Sandbox-dependent: churn (category bias / beneficiary-loser calcs stay
    # available on `run` for the results table, just not rendered as cards) ────
    run = state.sandbox_run
    if run and run.top10_turnover_pct > 40.0:
        card = render_insight_template("RULE_HIGH_CHURN_WARNING_V1", {
            **_base(), "top10_turnover_pct": round(run.top10_turnover_pct, 1),
            "top10_turnover_count": len(run.entering_funds),
            "average_rank_change": "n/a",
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

    if blocking:
        card = render_insight_template("RULE_NOT_READY_FOR_APPROVAL_V1", {
            **_base(), "blocking_issue_count": len(blocking),
            "weight_status": "valid" if weights_valid else "invalid",
            "formula_status": "valid" if formulas_valid else "invalid",
            "sandbox_status": "complete" if run else "not run",
        })
    else:
        card = render_insight_template("RULE_READY_FOR_APPROVAL_V1", {**_base()})
    if card:
        cards.append(card.model_dump())

    return cards
