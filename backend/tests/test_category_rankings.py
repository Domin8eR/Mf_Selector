"""
Integration tests — Category Rankings.

1. GET /rankings/category returns sorted + paginated results
2. GET /rankings/explain contribution sum ≈ composite_score (ε < 0.02)
3. One CAT_*_V1 template renders from seeded data
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

CAT = "Equity — Large Cap"
EPSILON = 0.02  # floating-point tolerance for contribution sum


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# ── 1. /rankings/category ────────────────────────────────────────────────────

def test_category_rankings_returns_200(client):
    r = client.get(f"/rankings/category?category={CAT}")
    assert r.status_code == 200, r.text


def test_category_rankings_sorted_by_rank(client):
    """Ranks must be monotonically increasing."""
    r = client.get(f"/rankings/category?category={CAT}&page_size=50")
    data = r.json()
    ranks = [f["rank"] for f in data["results"]]
    assert ranks == sorted(ranks), f"Ranks are not sorted: {ranks[:10]}"


def test_category_rankings_scores_descending(client):
    """Composite scores must be non-increasing (higher rank = higher score)."""
    r = client.get(f"/rankings/category?category={CAT}&page_size=50")
    data = r.json()
    scores = [f["composite_score"] for f in data["results"]]
    # Allow small floating-point ties
    for i in range(len(scores) - 1):
        assert scores[i] >= scores[i + 1] - EPSILON, (
            f"Score not descending at index {i}: {scores[i]} < {scores[i+1]}"
        )


def test_category_rankings_pagination(client):
    """page=1 and page=2 must return non-overlapping results."""
    r1 = client.get(f"/rankings/category?category={CAT}&page=1&page_size=10")
    r2 = client.get(f"/rankings/category?category={CAT}&page=2&page_size=10")
    ids1 = {f["schemecode"] for f in r1.json()["results"]}
    ids2 = {f["schemecode"] for f in r2.json()["results"]}
    assert not ids1.intersection(ids2), "Pages overlap in schemecodes"


def test_category_rankings_status_labels_present(client):
    r = client.get(f"/rankings/category?category={CAT}&page_size=20")
    data = r.json()
    valid = {"Strong", "Good", "Neutral", "Weak"}
    for fund in data["results"]:
        assert fund["status_label"] in valid, (
            f"Unexpected status label: {fund['status_label']}"
        )


def test_category_rankings_versioned_response(client):
    r = client.get(f"/rankings/category?category={CAT}")
    data = r.json()
    for field in ("data_version", "rule_version", "calculation_version",
                  "as_of_date", "evaluation_date"):
        assert field in data, f"Missing versioned field: {field}"


# ── 2. /rankings/explain ─────────────────────────────────────────────────────

def test_explain_rank_returns_200(client):
    # Get top-ranked fund from seeded data
    r = client.get(f"/rankings/category?category={CAT}&page_size=1")
    sc = r.json()["results"][0]["schemecode"]
    r2 = client.get(f"/rankings/explain/{sc}?category={CAT}")
    assert r2.status_code == 200, r2.text


def test_explain_contribution_sum_equals_composite_score(client):
    """
    Sum of component contributions must equal composite_score
    within floating-point epsilon.
    """
    r = client.get(f"/rankings/category?category={CAT}&page_size=5")
    for fund in r.json()["results"]:
        sc = fund["schemecode"]
        r2 = client.get(f"/rankings/explain/{sc}?category={CAT}")
        assert r2.status_code == 200
        d = r2.json()
        total_contrib = sum(c["contribution"] for c in d["components"])
        assert abs(total_contrib - d["composite_score"]) < EPSILON, (
            f"Fund {sc}: contribution_sum={total_contrib:.4f} "
            f"!= composite_score={d['composite_score']:.4f}"
        )


def test_explain_has_four_components(client):
    r = client.get(f"/rankings/category?category={CAT}&page_size=1")
    sc = r.json()["results"][0]["schemecode"]
    r2 = client.get(f"/rankings/explain/{sc}?category={CAT}")
    assert len(r2.json()["components"]) == 4


def test_explain_weights_sum_to_one(client):
    r = client.get(f"/rankings/category?category={CAT}&page_size=1")
    sc = r.json()["results"][0]["schemecode"]
    r2 = client.get(f"/rankings/explain/{sc}?category={CAT}")
    weights = [c["weight"] for c in r2.json()["components"]]
    assert abs(sum(weights) - 1.0) < 0.001, f"Weights don't sum to 1.0: {sum(weights)}"


# ── 3. /insights/category-rankings — CAT_*_V1 templates ─────────────────────

def test_category_insights_returns_200(client):
    r = client.get(f"/insights/category-rankings?category={CAT}")
    assert r.status_code == 200, r.text


def test_category_insights_v1_template_rendered(client):
    """At least one CAT_*_V1 template must be present."""
    r = client.get(f"/insights/category-rankings?category={CAT}")
    data = r.json()
    v1_cards = [
        c for c in data["cards"]
        if c["template_id"].startswith("CAT_") and c["template_id"].endswith("_V1")
    ]
    assert len(v1_cards) >= 1, (
        f"Expected at least one CAT_*_V1 card. Got: {[c['template_id'] for c in data['cards']]}"
    )


def test_category_insights_no_forbidden_language(client):
    """compact_text/expanded_bullets replaced headline/body_text in the
    2026-07-18 compact-card migration."""
    FORBIDDEN = {"buy", "sell", "recommend", "top pick", "best fund", "switch"}
    r = client.get(f"/insights/category-rankings?category={CAT}")
    for card in r.json()["cards"]:
        blob = (card["compact_text"] + " " + " ".join(card["expanded_bullets"])).lower()
        found = [w for w in FORBIDDEN if w in blob]
        assert not found, (
            f"Card '{card['template_id']}' contains forbidden words: {found}"
        )


def test_what_changed_has_three_tiles(client):
    r = client.get(f"/rankings/what-changed?category={CAT}")
    assert r.status_code == 200
    data = r.json()
    assert data["has_data"] is True
    assert len(data["tiles"]) == 3


def test_ranking_history_has_six_dates(client):
    r = client.get(f"/rankings/history?category={CAT}&top_n=5")
    assert r.status_code == 200
    data = r.json()
    assert len(data["dates"]) == 6, f"Expected 6 dates, got: {data['dates']}"
    assert len(data["series"]) == 5
