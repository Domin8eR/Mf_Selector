"""
Integration test: GET /insights/workspace/daily-briefing

Asserts that:
1. The endpoint returns HTTP 200.
2. At least one AIW_*_V1 template is rendered (uses real seeded snapshot data).
3. The summary card AIW_DAILY_BRIEFING_SUMMARY_V1 is always present.
4. Card bodies contain no forbidden language (buy/sell/recommend/top pick).
5. evaluation_date is returned.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

FORBIDDEN_WORDS = {"buy", "sell", "recommend", "top pick", "best fund", "switch"}
V1_TEMPLATE_PREFIX = "AIW_"
V1_TEMPLATE_SUFFIX = "_V1"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_daily_briefing_returns_200(client: TestClient):
    r = client.get("/insights/workspace/daily-briefing")
    assert r.status_code == 200, r.text


def test_daily_briefing_has_evaluation_date(client: TestClient):
    r = client.get("/insights/workspace/daily-briefing")
    data = r.json()
    assert "evaluation_date" in data
    assert data["evaluation_date"] is not None


def test_daily_briefing_summary_card_always_present(client: TestClient):
    r = client.get("/insights/workspace/daily-briefing")
    data = r.json()
    template_ids = [c["template_id"] for c in data["cards"]]
    assert "AIW_DAILY_BRIEFING_SUMMARY_V1" in template_ids, (
        "AIW_DAILY_BRIEFING_SUMMARY_V1 must always be emitted. "
        f"Got: {template_ids}"
    )


def test_daily_briefing_has_v1_templates(client: TestClient):
    """At least one V1 template is rendered from the seeded snapshot data."""
    r = client.get("/insights/workspace/daily-briefing")
    data = r.json()
    v1_cards = [
        c for c in data["cards"]
        if c["template_id"].startswith(V1_TEMPLATE_PREFIX)
        and c["template_id"].endswith(V1_TEMPLATE_SUFFIX)
    ]
    assert len(v1_cards) >= 1, (
        f"Expected at least one AIW_*_V1 card. Got: {[c['template_id'] for c in data['cards']]}"
    )


def test_daily_briefing_rank_improvers_template_rendered(client: TestClient):
    """AIW_RANK_IMPROVERS_COUNT_*_V1 must be present for each evaluated category."""
    r = client.get("/insights/workspace/daily-briefing")
    data = r.json()
    template_ids = [c["template_id"] for c in data["cards"]]
    count_templates = [
        t for t in template_ids
        if "RANK_IMPROVERS_COUNT" in t and t.endswith("_V1")
    ]
    # 3 categories → 3 count cards (positive or zero or snapshot-missing)
    assert len(count_templates) == 3, (
        f"Expected 3 rank-improver count cards (one per category). Got: {count_templates}"
    )


def test_daily_briefing_positive_improvers_have_count(client: TestClient):
    """AIW_RANK_IMPROVERS_COUNT_POSITIVE_V1 must carry count > 0 in its headline."""
    r = client.get("/insights/workspace/daily-briefing")
    data = r.json()
    for card in data["cards"]:
        if card["template_id"] == "AIW_RANK_IMPROVERS_COUNT_POSITIVE_V1":
            headline = card["headline"]
            # Headline format: "{count} fund(s) show structural improvement in {category}"
            assert "fund" in headline.lower(), f"Unexpected headline: {headline}"
            # Count must be a positive integer in the first token
            first_token = headline.split()[0]
            assert first_token.isdigit() and int(first_token) > 0, (
                f"Count in headline must be > 0, got: {headline}"
            )


def test_daily_briefing_no_forbidden_language(client: TestClient):
    """No card headline or body_text may contain forbidden investment-advice language."""
    r = client.get("/insights/workspace/daily-briefing")
    data = r.json()
    for card in data["cards"]:
        text_blob = (card["headline"] + " " + card["body_text"]).lower()
        found = [w for w in FORBIDDEN_WORDS if w in text_blob]
        assert not found, (
            f"Card '{card['template_id']}' contains forbidden words {found}. "
            f"Headline: {card['headline']}"
        )
