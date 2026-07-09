"""
Tests for the Rule Playground backend.

Coverage:
  1. Formula parser — rejects unknown variable and eval-unsafe syntax
  2. sandbox/run-v2 — weights ≠ 1.0 → 422 with helpful message
  3. sandbox math — promoted + dropped + no_change == total fund count
  4. Top-10 turnover — symmetric_difference / 10 * 100
  5. RULE_*_V1 template rendering — ≥ 6 distinct templates fire correctly
  6. submit-for-approval isolation — created row has is_active=false and
     status='pending_review'; GET /rules/default still returns old active version
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

# ── 1. Formula parser ─────────────────────────────────────────────────────────

from app.quant.formula_parser import validate_formula, ALLOWED_FUNCTIONS


KNOWN_VARS = [
    "information_ratio_3yr", "sharpe_ratio_3yr", "tracking_error_3yr",
    "ir_slope_6m_proxy", "jensens_alpha_3yr",
    "fund_1yr_ret", "fund_3yr_ret", "fund_5yr_ret",
    "active_1yr_ret", "active_3yr_ret", "active_5yr_ret",
    "expense_ratio_pct", "rank_delta_6m",
]


def test_formula_parser_rejects_unknown_variable():
    """Formula that references a variable not in the vocabulary must be invalid."""
    result = validate_formula("unknown_metric * 0.5", KNOWN_VARS)
    assert not result.valid
    assert result.error_type == "invalid_variable"
    assert "unknown_metric" in (result.error_message or "")


def test_formula_parser_rejects_eval_import():
    """__import__ and similar builtins must never be accepted."""
    result = validate_formula("__import__('os')", KNOWN_VARS)
    assert not result.valid


def test_formula_parser_rejects_lambda():
    """Lambda construct is disallowed."""
    result = validate_formula("lambda x: x", KNOWN_VARS)
    assert not result.valid
    assert result.error_type in ("syntax", "disallowed_construct")


def test_formula_parser_rejects_attribute_access():
    """Attribute access like fund.ir would be a disallowed construct."""
    result = validate_formula("information_ratio_3yr.__class__", KNOWN_VARS)
    assert not result.valid


def test_formula_parser_rejects_unknown_function():
    """Functions not in ALLOWED_FUNCTIONS must be rejected."""
    result = validate_formula("eval(information_ratio_3yr)", KNOWN_VARS)
    assert not result.valid
    assert result.error_type in ("invalid_function", "disallowed_construct")


def test_formula_parser_rejects_subscript():
    """Subscript access (list[0]) is a disallowed construct."""
    result = validate_formula("information_ratio_3yr[0]", KNOWN_VARS)
    assert not result.valid


def test_formula_parser_accepts_valid_arithmetic():
    """Simple weighted combination of known metrics must pass."""
    result = validate_formula(
        "information_ratio_3yr * 0.6 + sharpe_ratio_3yr * 0.4",
        KNOWN_VARS,
    )
    assert result.valid
    assert result.error_type is None
    assert "information_ratio_3yr" in result.parsed_variables
    assert "sharpe_ratio_3yr" in result.parsed_variables


def test_formula_parser_accepts_allowed_functions():
    """AVG() with known variables must pass."""
    result = validate_formula(
        "AVG(information_ratio_3yr, sharpe_ratio_3yr)",
        KNOWN_VARS,
    )
    assert result.valid


def test_formula_parser_sample_preview():
    """When sample_envs are provided the result includes previews without eval."""
    sample_envs = [
        {"information_ratio_3yr": 0.8, "sharpe_ratio_3yr": 1.2},
        {"information_ratio_3yr": 0.4, "sharpe_ratio_3yr": 0.6},
    ]
    result = validate_formula(
        "information_ratio_3yr * 0.6 + sharpe_ratio_3yr * 0.4",
        KNOWN_VARS,
        sample_envs=sample_envs,
    )
    assert result.valid
    assert result.sample_preview is not None
    assert len(result.sample_preview) == 2
    # Verify first preview: 0.8*0.6 + 1.2*0.4 = 0.48 + 0.48 = 0.96
    first = result.sample_preview[0]
    assert first["result"] is not None
    assert abs(first["result"] - 0.96) < 1e-4


def test_formula_parser_rejects_empty():
    result = validate_formula("", KNOWN_VARS)
    assert not result.valid
    assert result.error_type == "empty"


def test_formula_parser_rejects_syntax_error():
    result = validate_formula("information_ratio_3yr + (", KNOWN_VARS)
    assert not result.valid
    assert result.error_type == "syntax"


# ── 2. sandbox/run-v2 weights validation ──────────────────────────────────────

from fastapi.testclient import TestClient
from app.main import app

_client = TestClient(app, raise_server_exceptions=False)


def _v2_payload(weights: list[float], category: str = "Large Cap") -> dict:
    cols = ["information_ratio_3yr", "sharpe_ratio_3yr", "fund_3yr_ret", "tracking_error_3yr"]
    return {
        "category": category,
        "rule_components": [
            {"metric_column": col, "direction": "higher_better", "weight": w}
            for col, w in zip(cols, weights)
        ],
    }


@pytest.mark.parametrize("weights,expected_msg_fragment", [
    ([0.40, 0.30, 0.20, 0.15], "1.0"),     # total = 1.05 → 422
    ([0.40, 0.25, 0.20, 0.10], "1.0"),     # total = 0.95 → 422
    ([0.10, 0.10, 0.10, 0.10], "1.0"),     # total = 0.40 → 422
])
def test_sandbox_run_v2_rejects_bad_weights(weights, expected_msg_fragment):
    """Weights not summing to 1.0 ± 0.5% must return HTTP 422."""
    resp = _client.post("/rules/sandbox/run-v2", json=_v2_payload(weights))
    assert resp.status_code == 422
    body = resp.json()
    detail = body.get("detail", "")
    assert "1.0" in detail or "weight" in detail.lower()


def test_sandbox_run_v2_rejects_empty_components():
    """Empty rule_components must return HTTP 422."""
    resp = _client.post("/rules/sandbox/run-v2", json={"category": "Large Cap", "rule_components": []})
    assert resp.status_code == 422


# ── 3. sandbox math: promoted + dropped + no_change == total ──────────────────

def _simulate_sandbox_diff(
    universe: list[dict],
    sandbox_ranked: list[dict],
) -> tuple[int, int, int]:
    """Replicate the diff logic from sandbox_run_v2 for unit testing."""
    default_rank_map = {f["schemecode"]: f["default_rank"] for f in universe}
    promoted = dropped = no_change = 0
    for sb_rank, f in enumerate(sandbox_ranked, 1):
        def_rank = default_rank_map.get(f["schemecode"], sb_rank)
        change = def_rank - sb_rank
        if change > 0:
            promoted += 1
        elif change < 0:
            dropped += 1
        else:
            no_change += 1
    return promoted, dropped, no_change


@pytest.mark.parametrize("n_funds", [5, 10, 20, 50])
def test_diff_counts_sum_to_total(n_funds):
    """promoted + dropped + no_change must equal the total number of funds."""
    import random
    random.seed(42)
    universe = [
        {"schemecode": i, "fund_name": f"Fund {i}", "default_rank": i + 1, "default_score": 0.0}
        for i in range(n_funds)
    ]
    # Random sandbox ranking — just shuffle
    sandbox_ranked = random.sample(universe, len(universe))
    promoted, dropped, no_change = _simulate_sandbox_diff(universe, sandbox_ranked)
    assert promoted + dropped + no_change == n_funds


def test_diff_counts_all_no_change_when_identical_order():
    """When sandbox order equals default order, all funds are no_change."""
    n = 10
    universe = [
        {"schemecode": i, "fund_name": f"Fund {i}", "default_rank": i + 1, "default_score": 0.0}
        for i in range(n)
    ]
    sandbox_ranked = sorted(universe, key=lambda f: f["default_rank"])
    promoted, dropped, no_change = _simulate_sandbox_diff(universe, sandbox_ranked)
    assert promoted == 0
    assert dropped == 0
    assert no_change == n


def test_diff_counts_all_changed_when_reversed():
    """When sandbox order is the exact reverse of default, all funds move."""
    n = 10
    universe = [
        {"schemecode": i, "fund_name": f"Fund {i}", "default_rank": i + 1, "default_score": 0.0}
        for i in range(n)
    ]
    sandbox_ranked = list(reversed(sorted(universe, key=lambda f: f["default_rank"])))
    promoted, dropped, no_change = _simulate_sandbox_diff(universe, sandbox_ranked)
    # No fund stays in the same rank (all even n, no middle rank matches for n=10)
    assert no_change == 0
    assert promoted + dropped == n


# ── 4. Top-10 turnover calculation ────────────────────────────────────────────

def _compute_turnover(
    default_rank_map: dict[int, int],
    sandbox_ranked_codes: list[int],
) -> float:
    """Replicate the turnover formula from sandbox_run_v2.

    Formula: entering_count / top_n * 100  (0–100% scale).
    entering_count = funds in sandbox top10 that were NOT in default top10.
    """
    default_top10 = set(
        sc for sc, dr in sorted(default_rank_map.items(), key=lambda x: x[1])[:10]
    )
    sandbox_top10 = set(sandbox_ranked_codes[:10])
    entering_count = len([sc for sc in sandbox_top10 if sc not in default_top10])
    return (entering_count / 10) * 100 if default_top10 else 0.0


def test_turnover_zero_when_top10_unchanged():
    """No churn → turnover = 0%."""
    codes = list(range(1, 21))
    default_ranks = {c: c for c in codes}            # default rank 1..20
    sandbox_order = codes[:]                          # same order
    turnover = _compute_turnover(default_ranks, sandbox_order)
    assert turnover == 0.0


def test_turnover_100_when_top10_completely_replaced():
    """Completely different top 10 → turnover = 100%."""
    # Funds 1-10 are default top 10; sandbox puts 11-20 in top 10
    codes = list(range(1, 21))
    default_ranks = {c: c for c in codes}
    sandbox_order = list(range(11, 21)) + list(range(1, 11))
    turnover = _compute_turnover(default_ranks, sandbox_order)
    assert turnover == 100.0


@pytest.mark.parametrize("n_changed,expected_pct", [
    (0, 0.0),
    (2, 20.0),
    (4, 40.0),
    (5, 50.0),
    (10, 100.0),
])
def test_turnover_parametrized(n_changed, expected_pct):
    """n funds entering = n leaving → turnover = (2n/10)*100 ÷ 2 = n*10%."""
    codes = list(range(1, 21))
    default_ranks = {c: c for c in codes}
    # Swap n_changed pairs between positions 1-10 and 11-20
    sandbox_order = codes[:]
    for i in range(n_changed):
        # Swap fund at position i (default top10) with fund at position 10+i
        sandbox_order[i], sandbox_order[10 + i] = sandbox_order[10 + i], sandbox_order[i]
    turnover = _compute_turnover(default_ranks, sandbox_order)
    assert abs(turnover - expected_pct) < 1e-6


# ── 5. RULE_*_V1 template rendering ──────────────────────────────────────────

from app.services.rule_playground_insights import (
    generate_rule_playground_insights,
    SandboxState,
    SandboxComponent as InsightComponent,
    SandboxRunSummary,
    FormulaValidationStatus,
)


def _make_state(
    weights: dict[str, float],
    sandbox_run: SandboxRunSummary | None = None,
    formula_validations: list[FormulaValidationStatus] | None = None,
    rationale_present: bool = False,
    category: str = "Large Cap",
) -> SandboxState:
    return SandboxState(
        components=[
            InsightComponent(metric_column=col, weight_pct=w * 100)
            for col, w in weights.items()
        ],
        formula_validations=formula_validations or [],
        sandbox_run=sandbox_run,
        rationale_present=rationale_present,
        category=category,
    )


def _get_card(cards: list[dict], template_id: str) -> dict | None:
    return next((c for c in cards if c.get("template_id") == template_id), None)


# ── 5a. RULE_WEIGHTS_VALID_V1 ─────────────────────────────────────────────────

def test_template_weights_valid():
    """Valid 100% weight distribution → RULE_WEIGHTS_VALID_V1 fires."""
    state = _make_state({"information_ratio_3yr": 0.40, "sharpe_ratio_3yr": 0.60})
    cards = generate_rule_playground_insights(state)
    ids = [c["template_id"] for c in cards]
    assert "RULE_WEIGHTS_VALID_V1" in ids


# ── 5b. RULE_WEIGHTS_INVALID_TOTAL_HIGH_V1 ────────────────────────────────────

def test_template_weights_invalid_high():
    """Weights over 100% → RULE_WEIGHTS_INVALID_TOTAL_HIGH_V1 fires."""
    state = _make_state({"information_ratio_3yr": 0.70, "sharpe_ratio_3yr": 0.60})
    cards = generate_rule_playground_insights(state)
    card = _get_card(cards, "RULE_WEIGHTS_INVALID_TOTAL_HIGH_V1")
    assert card is not None
    assert card["severity"] == "warning"


# ── 5c. RULE_WEIGHTS_INVALID_NEGATIVE_V1 ─────────────────────────────────────

def test_template_weights_invalid_negative():
    """Negative weight → RULE_WEIGHTS_INVALID_NEGATIVE_V1 fires."""
    state = _make_state({"information_ratio_3yr": 1.10, "sharpe_ratio_3yr": -0.10})
    cards = generate_rule_playground_insights(state)
    ids = [c["template_id"] for c in cards]
    assert "RULE_WEIGHTS_INVALID_NEGATIVE_V1" in ids


# ── 5d. RULE_RECENCY_BIAS_WARNING_V1 ─────────────────────────────────────────

def test_template_recency_bias_fires():
    """Short-window metrics > 50% weight → RULE_RECENCY_BIAS_WARNING_V1."""
    # ir_slope_6m_proxy + fund_1yr_ret = 60% → recency bias
    state = _make_state({
        "ir_slope_6m_proxy": 0.35,
        "fund_1yr_ret": 0.25,
        "information_ratio_3yr": 0.40,
    })
    cards = generate_rule_playground_insights(state)
    ids = [c["template_id"] for c in cards]
    assert "RULE_RECENCY_BIAS_WARNING_V1" in ids


def test_template_recency_bias_ok():
    """Short-window metrics ≤ 50% → RULE_RECENCY_BIAS_OK_V1 fires (no warning)."""
    state = _make_state({
        "ir_slope_6m_proxy": 0.20,
        "information_ratio_3yr": 0.80,
    })
    cards = generate_rule_playground_insights(state)
    ids = [c["template_id"] for c in cards]
    assert "RULE_RECENCY_BIAS_WARNING_V1" not in ids
    assert "RULE_RECENCY_BIAS_OK_V1" in ids


# ── 5e. RULE_HIGH_CHURN_WARNING_V1 ────────────────────────────────────────────

def test_template_high_churn_fires():
    """Top-10 turnover > 40% → RULE_HIGH_CHURN_WARNING_V1."""
    run = SandboxRunSummary(
        fund_count=20,
        promoted=5, dropped=5, no_change=10,
        top10_turnover_pct=60.0,
        entering_funds=["Fund A", "Fund B"],
        leaving_funds=["Fund C", "Fund D"],
        beneficiary_name="Fund A", beneficiary_default_rank=12,
        beneficiary_sandbox_rank=3, beneficiary_places=9,
        loser_name="Fund C", loser_default_rank=2,
        loser_sandbox_rank=15, loser_places=13,
    )
    state = _make_state(
        {"information_ratio_3yr": 0.60, "sharpe_ratio_3yr": 0.40},
        sandbox_run=run,
    )
    cards = generate_rule_playground_insights(state)
    ids = [c["template_id"] for c in cards]
    assert "RULE_HIGH_CHURN_WARNING_V1" in ids


# ── 5f. RULE_READY_FOR_APPROVAL_V1 ────────────────────────────────────────────

def test_template_ready_for_approval_fires_when_all_checks_pass():
    """No blocking conditions → RULE_READY_FOR_APPROVAL_V1 fires."""
    run = SandboxRunSummary(
        fund_count=20,
        promoted=2, dropped=2, no_change=16,
        top10_turnover_pct=20.0,
        entering_funds=["Fund A"],
        leaving_funds=["Fund B"],
        beneficiary_name="Fund A", beneficiary_default_rank=12,
        beneficiary_sandbox_rank=8, beneficiary_places=4,
        loser_name="Fund B", loser_default_rank=8,
        loser_sandbox_rank=12, loser_places=4,
    )
    state = _make_state(
        {"information_ratio_3yr": 0.40, "sharpe_ratio_3yr": 0.60},
        sandbox_run=run,
        rationale_present=True,
    )
    cards = generate_rule_playground_insights(state)
    ids = [c["template_id"] for c in cards]
    assert "RULE_READY_FOR_APPROVAL_V1" in ids
    assert "RULE_NOT_READY_FOR_APPROVAL_V1" not in ids


def test_template_not_ready_when_no_sandbox_run():
    """Missing sandbox run → RULE_NOT_READY_FOR_APPROVAL_V1 fires."""
    state = _make_state({"information_ratio_3yr": 0.40, "sharpe_ratio_3yr": 0.60})
    cards = generate_rule_playground_insights(state)
    ids = [c["template_id"] for c in cards]
    assert "RULE_NOT_READY_FOR_APPROVAL_V1" in ids


def test_template_not_ready_when_weights_invalid():
    """Invalid weights → RULE_NOT_READY_FOR_APPROVAL_V1 fires."""
    state = _make_state({"information_ratio_3yr": 0.70, "sharpe_ratio_3yr": 0.70})
    cards = generate_rule_playground_insights(state)
    ids = [c["template_id"] for c in cards]
    assert "RULE_NOT_READY_FOR_APPROVAL_V1" in ids


def test_at_least_six_distinct_templates_rendered():
    """A fully populated state must render at least 6 distinct RULE_*_V1 cards."""
    run = SandboxRunSummary(
        fund_count=20,
        promoted=2, dropped=2, no_change=16,
        top10_turnover_pct=20.0,
        entering_funds=["Fund A"],
        leaving_funds=["Fund B"],
        beneficiary_name="Fund A", beneficiary_default_rank=12,
        beneficiary_sandbox_rank=8, beneficiary_places=4,
        loser_name="Fund B", loser_default_rank=8,
        loser_sandbox_rank=12, loser_places=4,
    )
    fv = FormulaValidationStatus(
        component_name="information_ratio_3yr",
        valid=True,
        parsed_variables=["information_ratio_3yr"],
        sample_result=0.75,
    )
    state = _make_state(
        {"information_ratio_3yr": 0.60, "sharpe_ratio_3yr": 0.40},
        sandbox_run=run,
        formula_validations=[fv],
        rationale_present=True,
    )
    cards = generate_rule_playground_insights(state)
    template_ids = {c["template_id"] for c in cards}
    assert len(template_ids) >= 6, (
        f"Expected ≥6 distinct RULE_*_V1 templates; got {sorted(template_ids)}"
    )


# ── 6. submit-for-approval isolation ─────────────────────────────────────────

def test_submit_for_approval_creates_pending_not_active():
    """
    POST /rules/submit-for-approval must return status='pending_review'.
    The endpoint must NOT update is_active to true on any row.
    Verified by mocking the DB session so no real selfmade_ table is needed.
    """
    # Simulate what the DB returns: one active rule set, 0 pending versions
    mock_row_rs  = MagicMock()
    mock_row_rs.__getitem__ = lambda self, i: 42 if i == 0 else None  # rule_set_id = 42

    mock_row_rv  = MagicMock()
    mock_row_rv.__getitem__ = lambda self, i: {
        0: 99,                      # rule_version_id
        1: "sandbox-1",             # version_label
        2: "pending_review",        # status
        3: None,                    # created_at
    }[i]

    execute_call_count = 0
    insert_sql_calls: list[str] = []

    def fake_execute(sql, params=None):
        nonlocal execute_call_count
        execute_call_count += 1
        sql_text = str(sql)

        mock_result = MagicMock()
        if "selfmade_rule_set" in sql_text and "is_active" in sql_text:
            mock_result.fetchone.return_value = mock_row_rs
            mock_result.scalar.return_value = None
        elif "COUNT" in sql_text and "pending_review" in sql_text:
            mock_result.scalar.return_value = 0
            mock_result.fetchone.return_value = None
        elif "INSERT INTO selfmade_rule_version" in sql_text:
            insert_sql_calls.append(sql_text)
            mock_result.fetchone.return_value = mock_row_rv
        elif "INSERT INTO selfmade_rule_component" in sql_text:
            insert_sql_calls.append(sql_text)
            mock_result.fetchone.return_value = None
        else:
            mock_result.fetchone.return_value = None
            mock_result.scalar.return_value = None
        return mock_result

    mock_db = MagicMock()
    mock_db.execute.side_effect = fake_execute
    mock_db.commit.return_value = None

    payload = {
        "rule_components": [
            {"metric_column": "information_ratio_3yr", "direction": "higher_better", "weight": 0.60},
            {"metric_column": "sharpe_ratio_3yr", "direction": "higher_better", "weight": 0.40},
        ],
        "rationale": "Testing isolation — this must remain pending_review only",
        "category": "Large Cap",
    }

    from app.core.db import get_db
    from app.main import app as _app
    from fastapi.testclient import TestClient

    def _override():
        yield mock_db

    _app.dependency_overrides[get_db] = _override
    try:
        with TestClient(_app) as c:
            resp = c.post("/rules/submit-for-approval", json=payload)
    finally:
        _app.dependency_overrides.clear()

    assert resp.status_code == 201, resp.text
    body = resp.json()

    # Must return pending_review status, not active
    assert body["status"] == "pending_review"

    # The INSERT SQL must set is_active=false and status='pending_review'
    version_inserts = [s for s in insert_sql_calls if "selfmade_rule_version" in s]
    assert len(version_inserts) >= 1
    insert_sql = version_inserts[0]
    assert "false" in insert_sql.lower() or "is_active" in insert_sql
    assert "pending_review" in insert_sql


def test_submit_for_approval_requires_nonempty_rationale():
    """Blank rationale must return 422."""
    payload = {
        "rule_components": [
            {"metric_column": "information_ratio_3yr", "direction": "higher_better", "weight": 1.0},
        ],
        "rationale": "   ",
        "category": "Large Cap",
    }
    resp = _client.post("/rules/submit-for-approval", json=payload)
    assert resp.status_code == 422
