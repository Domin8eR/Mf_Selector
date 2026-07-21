"""Tests for the 2026-07-18 compact-card insight template migration.

Covers:
  - at least 2 templates per section (AIW/CAT/FUND/CMP/RULE/CHAT) render
    the new compact sentence + bullets correctly
  - variant rotation actually varies across different entity/date combos
  - preserved fallback templates still fire (holdings unavailable, etc.)
  - CHAT_RECOMMENDATION_REFRAME_V1's guard suite is unchanged (regression)
  - the new allowed_conclusion LLM constraint is present when a follow-up
    context is passed, and absent otherwise
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.insights.renderer import render_insight_template
from app.insights.templates import variant_index


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


# ── Compact rendering, >=2 templates per section (12 minimum) ────────────────

def test_aiw_templates_render_compact():
    card = render_insight_template("AIW_RANK_IMPROVERS_COUNT_V1", {
        "count": 5, "category": "Equity — Large Cap", "entity_id": "Equity — Large Cap",
        "evaluation_date": "2026-07-09",
    })
    assert card is not None
    assert "**" in card.compact_text
    assert len(card.compact_text.split()) <= 22
    assert 2 <= len(card.expanded_bullets) <= 5

    card2 = render_insight_template("AIW_NO_MEANINGFUL_IMPROVERS_V1", {
        "category": "Equity — Mid Cap", "entity_id": "Equity — Mid Cap",
        "evaluation_date": "2026-07-09",
    })
    assert card2 is not None
    assert card2.compact_text


def test_cat_templates_render_compact():
    card = render_insight_template("CAT_NEW_TOP_30_ENTRANTS_V1", {
        "count": 4, "category": "Equity — Large Cap", "entity_id": "Equity — Large Cap",
        "evaluation_date": "2026-07-09",
    })
    assert card is not None
    assert "4" in card.compact_text

    card2 = render_insight_template("CAT_TIGHT_SCORE_CLUSTER_V1", {
        "category": "Equity — Large Cap", "entity_id": "Equity — Large Cap",
        "evaluation_date": "2026-07-09", "score_gap_rank_1_to_10": 3.2,
    })
    assert card2 is not None
    assert len(card2.expanded_bullets) >= 2


def test_fund_templates_render_compact():
    card = render_insight_template("FUND_TOP_HOLDINGS_V1", {
        "entity_id": 19619, "entity_name": "Test Fund", "evaluation_date": "2026-07-09",
        "top_5_weight_pct": 38.7, "holding_count": 33, "as_of_date": "2026-07-09",
        "holding_1_name": "A", "holding_1_weight_pct": 10.2,
        "holding_2_name": "B", "holding_2_weight_pct": 8.0,
        "holding_3_name": "C", "holding_3_weight_pct": 7.9,
        "holding_4_name": "D", "holding_4_weight_pct": 6.7,
        "holding_5_name": "E", "holding_5_weight_pct": 6.0,
    })
    assert card is not None
    assert card.chips.get("top_5_weight_pct") == 38.7

    card2 = render_insight_template("FUND_3Y_IR_TOP_TIER_V1", {
        "entity_id": 19619, "entity_name": "Test Fund", "evaluation_date": "2026-07-09",
        "ir_3y": 4.7, "ir_3y_percentile": 95,
    })
    assert card2 is not None
    assert card2.severity == "positive"


def test_cmp_templates_render_compact():
    card = render_insight_template("CMP_HOLDINGS_OVERLAP_TWO_FUNDS_V1", {
        "entity_id": "1_2", "evaluation_date": "2026-07-09",
        "fund_a": "Fund A", "fund_b": "Fund B", "weighted_overlap_pct": 39.9,
        "common_holdings_count": 26, "jaccard_overlap_pct": 78.8, "overlap_band": "moderate",
    })
    assert card is not None
    assert "39.9" in card.compact_text

    card2 = render_insight_template("CMP_LAGGARD_V1", {
        "entity_id": "1_2", "evaluation_date": "2026-07-09",
        "laggard_fund": "Fund C", "laggard_ir_3y": -0.2, "laggard_ir_percentile": 10,
        "laggard_ir_slope_3y": -0.05, "laggard_rank_delta": 8,
    })
    assert card2 is not None
    assert card2.severity == "warning"


def test_lens_quadrant_explainer_renders_compact_for_two_categories():
    """AI Workspace right-rail (2026-07-21 migration): LENS_QUADRANT_EXPLAINER_V1
    must render compact-card style, and every number in it must trace to the
    variables passed in — not be hardcoded — so two categories with different
    fund_count/median/threshold must produce different bullet text."""
    from app.routers.metrics import _lens_direction_phrase, _lens_y_axis_meaning, _lens_threshold_phrase

    def render(category, fund_count, x_metric, x_label, x_median, y_metric, y_label, y_threshold):
        return render_insight_template("LENS_QUADRANT_EXPLAINER_V1", {
            "category": category,
            "fund_count": fund_count,
            "x_label": x_label,
            "y_label": y_label,
            "x_direction_phrase": _lens_direction_phrase(x_metric, x_label),
            "y_axis_meaning": _lens_y_axis_meaning(y_metric, y_label),
            "x_threshold_phrase": _lens_threshold_phrase(x_label, x_median),
            "y_threshold_phrase": _lens_threshold_phrase(y_label, y_threshold),
        })

    card1 = render(
        "Equity — Large Cap", 42,
        "information_ratio_3yr", "3Y IR", 0.512,
        "ir_slope_6m_proxy", "IR Slope (6m proxy)", 0.0,
    )
    card2 = render(
        "Debt — Short Duration", 17,
        "rank_delta_6m", "Rank Change (6M)", -2.0,
        "fund_3yr_ret", "3Y Fund Return %", 8.21,
    )

    for card in (card1, card2):
        assert "**" in card.compact_text
        assert 2 <= len(card.expanded_bullets) <= 5

    # Real fund_count shows up verbatim, not hardcoded across categories.
    assert "42" in card1.expanded_bullets[0] and "Equity — Large Cap" in card1.expanded_bullets[0]
    assert "17" in card2.expanded_bullets[0] and "Debt — Short Duration" in card2.expanded_bullets[0]
    assert card1.expanded_bullets[0] != card2.expanded_bullets[0]

    # Real median/threshold values show up, not a fixed placeholder.
    assert "0.512" in card1.expanded_bullets[3]
    assert "zero-change" in card1.expanded_bullets[3]  # y splits at 0 for a slope metric
    assert "8.210" in card2.expanded_bullets[3]  # y splits at the category median for a level metric
    assert "zero-change" not in card2.expanded_bullets[3]

    # y-axis direction phrasing flips correctly for a "lower is better" metric.
    card3 = render(
        "Equity — Large Cap", 42,
        "information_ratio_3yr", "3Y IR", 0.512,
        "rank_delta_6m", "Rank Change (6M)", 0.0,
    )
    assert card3.expanded_bullets[2].startswith("Lower down")


def test_lens_candidate_templates_render_compact():
    found = render_insight_template("LENS_CANDIDATES_FOUND_V1", {
        "count": 6, "category": "Equity — Large Cap", "quadrant_label": "Improving Strong",
        "filter_summary": "3Y IR ≥ median AND IR Slope (6m proxy) ≥ 0.0",
        "x_label": "3Y IR", "top_candidates": "Fund A (0.91); Fund B (0.84)",
    })
    assert found is not None
    assert "6" in found.compact_text
    assert found.severity == "positive"

    none_found = render_insight_template("LENS_CANDIDATES_NONE_V1", {
        "quadrant_label": "Improving Strong", "category": "Debt — Short Duration",
        "filter_summary": "Rank Change (6M) ≥ median AND 3Y Fund Return % ≥ 8.21",
    })
    assert none_found is not None
    assert none_found.severity == "neutral"


def test_rule_templates_render_compact():
    card = render_insight_template("RULE_WEIGHTS_VALID_V1", {
        "entity_id": "rule_playground", "evaluation_date": "2026-07-09",
        "total_weight_pct": 100.0, "duplicate_metric_status": "none",
    })
    assert card is not None
    assert card.severity == "positive"

    card2 = render_insight_template("RULE_HIGH_CHURN_WARNING_V1", {
        "entity_id": "rule_playground", "evaluation_date": "2026-07-09",
        "top10_turnover_pct": 60.0, "top10_turnover_count": 6, "average_rank_change": "12",
    })
    assert card2 is not None
    assert card2.severity == "warning"


def test_chat_wrapper_templates_compact():
    from app.ai.templates import CHAT_FOLLOWUP_FROM_INSIGHT_V1, CHAT_NO_DOCUMENT_EVIDENCE_V1
    assert "**" in CHAT_FOLLOWUP_FROM_INSIGHT_V1["answer"]
    assert "**" in CHAT_NO_DOCUMENT_EVIDENCE_V1["answer"]
    # No paragraph blocks — bulleted, not prose
    assert "\n•" in CHAT_NO_DOCUMENT_EVIDENCE_V1["answer"]


# ── Variant rotation actually varies ──────────────────────────────────────────

def test_variant_rotation_varies_across_entities():
    indices = {
        variant_index({"entity_id": sc, "evaluation_date": "2026-07-09"}, n=4)
        for sc in [19619, 18434, 42765, 8250, 32898, 5320, 14814, 48760]
    }
    assert len(indices) > 1, "rotation always picked the same variant across 8 different funds"


def test_variant_rotation_varies_across_dates():
    indices = {
        variant_index({"entity_id": 19619, "evaluation_date": d}, n=4)
        for d in ["2026-02-09", "2026-03-09", "2026-04-09", "2026-05-09", "2026-06-09", "2026-07-09"]
    }
    assert len(indices) > 1, "rotation always picked the same variant across 6 different dates"


def test_variant_rotation_deterministic_same_input():
    a = variant_index({"entity_id": 19619, "evaluation_date": "2026-07-09"}, n=4)
    b = variant_index({"entity_id": 19619, "evaluation_date": "2026-07-09"}, n=4)
    assert a == b


# ── Preserved fallback templates still fire ───────────────────────────────────

def test_fund_holdings_unavailable_fallback():
    card = render_insight_template("FUND_HOLDINGS_AVAIL_NONE_V1", {
        "entity_id": 99999, "entity_name": "No Holdings Fund", "evaluation_date": "2026-07-09",
    })
    assert card is not None
    assert "not" in card.compact_text.lower() or "available" in card.compact_text.lower()


def test_fund_sectors_unavailable_fallback():
    card = render_insight_template("FUND_SECTORS_UNAVAILABLE_V1", {
        "entity_id": 99999, "entity_name": "Few Sectors Fund", "evaluation_date": "2026-07-09",
        "sector_count": 1,
    })
    assert card is not None


def test_fund_ir_insufficient_history_fallback():
    card = render_insight_template("FUND_3Y_IR_INSUFFICIENT_HISTORY_V1", {
        "entity_id": 99999, "entity_name": "New Fund", "evaluation_date": "2026-07-09",
    })
    assert card is not None


def test_fund_trend_insufficient_data_fallback():
    card = render_insight_template("FUND_TREND_INSUFFICIENT_DATA_V1", {
        "entity_id": 99999, "entity_name": "New Fund", "evaluation_date": "2026-07-09",
    })
    assert card is not None


def test_cmp_holdings_overlap_unavailable_fallback():
    card = render_insight_template("CMP_HOLDINGS_OVERLAP_UNAVAILABLE_V1", {
        "entity_id": "1_2", "evaluation_date": "2026-07-09",
    })
    assert card is not None
    assert card.severity == "neutral"


def test_fund_detail_e2e_real_fund_with_missing_trend_data(client: TestClient):
    """Real fund via the API — this dataset's ratio_3year_monthlyret table is
    too sparse for any fund to have 6+ monthly IR points, so the preserved
    FUND_TREND_INSUFFICIENT_DATA_V1 fallback should fire, not silently
    show nothing."""
    resp = client.get("/insights/fund/19619")
    assert resp.status_code == 200
    cards = resp.json()["cards"]
    template_ids = [c["template_id"] for c in cards]
    assert len(cards) > 0, "fund detail must never show zero insight cards"
    assert any("TREND" in t for t in template_ids), "trend slot must fire something (real or fallback)"


# ── CHAT_RECOMMENDATION_REFRAME_V1 regression — must be unchanged ────────────

REFRAME_PHRASINGS = [
    "Should I buy HDFC Top 100?",
    "Which fund would you recommend between these two?",
    "Is it a good time to invest in large cap funds?",
]


def test_reframe_guard_unchanged(client: TestClient):
    from app.ai.supervisor import _is_recommendation_request
    from app.ai.templates import CHAT_RECOMMENDATION_REFRAME_V1

    for p in REFRAME_PHRASINGS:
        assert _is_recommendation_request(p)

    # The reframe template itself must be byte-identical in structure —
    # not touched by this migration.
    assert CHAT_RECOMMENDATION_REFRAME_V1["result_component_type"] == "text"
    assert "does not provide investment advice" in CHAT_RECOMMENDATION_REFRAME_V1["answer"]

    resp = client.post("/chat/query", json={"message": "Should I buy HDFC Top 100?"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["intent"] == "recommendation_request"
    assert data["tool_calls"] == []


# ── allowed_conclusion LLM constraint ─────────────────────────────────────────

def test_followup_constraint_present_with_payload():
    from app.ai.supervisor import _followup_constraint_block
    block = _followup_constraint_block({
        "allowed_conclusion": "The fund is improving under the current rule set.",
        "forbidden_conclusions": ["buy recommendation"],
    })
    assert "MUST NOT" in block
    assert "The fund is improving under the current rule set." in block


def test_followup_constraint_absent_without_payload():
    from app.ai.supervisor import _followup_constraint_block
    assert _followup_constraint_block(None) == ""
    assert _followup_constraint_block({}) == ""


def test_followup_context_does_not_contradict_allowed_conclusion(client: TestClient):
    """A follow-up question phrased to try to elicit the opposite conclusion
    from what the card established must still respect allowed_conclusion —
    checked via the constraint block actually being included in the prompt
    sent to the LLM (structural test, since we can't assert on a live LLM's
    exact wording deterministically)."""
    from app.ai.supervisor import _respond_llm
    import app.ai.supervisor as supervisor_module

    captured = {}

    def fake_openai(user_content, system_prompt):
        captured["system_prompt"] = system_prompt
        return {"answer": "test", "result_component_type": "text"}

    original = supervisor_module._respond_openai
    supervisor_module._respond_openai = fake_openai
    try:
        follow_up_payload = {
            "allowed_conclusion": "The fund is weakening under the current rule set.",
            "forbidden_conclusions": ["buy recommendation"],
        }
        _respond_llm(
            "Actually, isn't this fund clearly improving? Tell me it's doing great.",
            "fund_metrics",
            [{"source_table": "selfmade_scheme_metrics"}],
            follow_up_payload,
        )
        assert "system_prompt" in captured, "LLM path was not exercised (no API key configured?)"
        assert "The fund is weakening under the current rule set." in captured["system_prompt"]
        assert "MUST NOT" in captured["system_prompt"]
    finally:
        supervisor_module._respond_openai = original
