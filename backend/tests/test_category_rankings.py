"""
Integration tests — Category Rankings.

1. GET /rankings/category returns sorted + paginated results
2. GET /rankings/explain contribution sum ≈ composite_score (ε < 0.02)
3. One CAT_*_V1 template renders from seeded data
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.core.config import settings
from app.routers.rankings import CATEGORY_TAXONOMY

CAT = "Equity — Large Cap"
# /rankings/category reads selfmade_ranking_snapshot (bucket_36-keyed),
# populated by app.rankings.recompute.recompute_all_rankings() — the one
# governed formula, requiring ALL of the active rule version's components
# to be real (no fabricated neutral-percentile fallback for missing data).
# RANKING_CAT below uses the real bucket_36 taxonomy value. /explain,
# /what-changed, /history, and /insights/category-rankings still key off
# CAT (the legacy "Equity — X" string) for their trend history — real
# trend only exists for categories that have been recomputed more than once.
RANKING_CAT = "Large Cap"
EPSILON = 0.02  # floating-point tolerance for contribution sum


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def db():
    engine = create_engine(settings.database_url)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


# ── 1. /rankings/category ────────────────────────────────────────────────────

def test_category_rankings_returns_200(client):
    r = client.get(f"/rankings/category?category={RANKING_CAT}")
    assert r.status_code == 200, r.text


def test_category_rankings_sorted_by_rank(client):
    """Ranks must be monotonically increasing."""
    r = client.get(f"/rankings/category?category={RANKING_CAT}&page_size=50")
    data = r.json()
    ranks = [f["rank"] for f in data["results"]]
    assert ranks == sorted(ranks), f"Ranks are not sorted: {ranks[:10]}"


def test_category_rankings_scores_descending(client):
    """Composite scores must be non-increasing (higher rank = higher score)."""
    r = client.get(f"/rankings/category?category={RANKING_CAT}&page_size=50")
    data = r.json()
    scores = [f["composite_score"] for f in data["results"]]
    # Allow small floating-point ties
    for i in range(len(scores) - 1):
        assert scores[i] >= scores[i + 1] - EPSILON, (
            f"Score not descending at index {i}: {scores[i]} < {scores[i+1]}"
        )


def test_category_rankings_pagination(client):
    """page=1 and page=2 must return non-overlapping results."""
    r1 = client.get(f"/rankings/category?category={RANKING_CAT}&page=1&page_size=10")
    r2 = client.get(f"/rankings/category?category={RANKING_CAT}&page=2&page_size=10")
    ids1 = {f["schemecode"] for f in r1.json()["results"]}
    ids2 = {f["schemecode"] for f in r2.json()["results"]}
    assert not ids1.intersection(ids2), "Pages overlap in schemecodes"


def test_category_rankings_status_labels_present(client):
    r = client.get(f"/rankings/category?category={RANKING_CAT}&page_size=20")
    data = r.json()
    valid = {"Strong", "Good", "Neutral", "Weak"}
    for fund in data["results"]:
        assert fund["status_label"] in valid, (
            f"Unexpected status label: {fund['status_label']}"
        )


def test_category_rankings_versioned_response(client):
    r = client.get(f"/rankings/category?category={RANKING_CAT}")
    data = r.json()
    for field in ("data_version", "rule_version", "calculation_version",
                  "as_of_date", "evaluation_date"):
        assert field in data, f"Missing versioned field: {field}"


# ── 2. /rankings/explain ─────────────────────────────────────────────────────
# explain/what-changed/history read the legacy snapshot subset, keyed off CAT
# (the old "Equity — X" string) — Large Cap's schemecodes are an exact subset
# there, so a schemecode found via the new /rankings/category (RANKING_CAT)
# always has a matching legacy snapshot row for CAT.

def test_explain_rank_returns_200(client):
    # Get top-ranked fund from seeded data
    r = client.get(f"/rankings/category?category={RANKING_CAT}&page_size=1")
    sc = r.json()["results"][0]["schemecode"]
    r2 = client.get(f"/rankings/explain/{sc}?category={CAT}")
    assert r2.status_code == 200, r2.text


def test_explain_contribution_sum_equals_composite_score(client):
    """
    Sum of component contributions must equal composite_score
    within floating-point epsilon.
    """
    r = client.get(f"/rankings/category?category={RANKING_CAT}&page_size=5")
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
    r = client.get(f"/rankings/category?category={RANKING_CAT}&page_size=1")
    sc = r.json()["results"][0]["schemecode"]
    r2 = client.get(f"/rankings/explain/{sc}?category={CAT}")
    assert len(r2.json()["components"]) == 4


def test_explain_weights_sum_to_one(client):
    r = client.get(f"/rankings/category?category={RANKING_CAT}&page_size=1")
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


def test_ranking_history_survives_category_taxonomy_rename(client):
    """
    /rankings/history must match funds by schemecode across snapshot_date,
    not by literal category-string equality — category_taxonomy_current
    was renamed partway through this build ("Equity — Large Cap" ->
    "Large Cap"), and the real frontend always calls this endpoint with
    the CURRENT taxonomy value (RANKING_CAT), never the legacy CAT string.
    Before this was fixed, filtering on the raw category column silently
    truncated Large Cap to its single most-recent snapshot (2026-07-19)
    and hid 6 real months of prior history filed under "Equity — Large Cap".
    """
    r = client.get(f"/rankings/history?category={RANKING_CAT}&top_n=5")
    assert r.status_code == 200
    data = r.json()
    assert len(data["dates"]) >= 7, (
        f"Expected the full real history (>=7 monthly snapshots), got: {data['dates']}"
    )
    assert len(data["series"]) == 5


def test_ranking_history_latest_mode_returns_exactly_top_n(client):
    """mode=latest (default, used by the unchanged Rank History chart) is
    scoped to the top-N funds as of the most recent snapshot only."""
    r = client.get(f"/rankings/history?category={RANKING_CAT}&top_n=10&mode=latest")
    data = r.json()
    assert len(data["series"]) == 10
    for s in data["series"]:
        assert s["latest_rank"] is not None and s["latest_rank"] <= 10


def test_ranking_history_union_mode_can_exceed_top_n(client):
    """mode=union (Score History) is the union of top-N sets across every
    real snapshot date — if top-N membership shifted month to month, this
    naturally produces more than N funds. That's expected, not a bug."""
    r = client.get(f"/rankings/history?category={RANKING_CAT}&top_n=10&mode=union")
    data = r.json()
    assert len(data["series"]) > 10, (
        "Expected top-10 union across 7 real months to exceed 10 funds "
        f"(membership shifted); got {len(data['series'])}"
    )
    # Funds no longer in the top-10 as of the latest snapshot are still
    # included (real gap in their line, not silently dropped).
    assert any(s["latest_rank"] is None or s["latest_rank"] > 10 for s in data["series"])


def test_ranking_history_no_fabricated_scores_for_gaps(client):
    """
    Every data point's composite_score must be either a real float or None
    (a real gap) — never a fabricated/interpolated placeholder. Large Cap's
    specific top-10 union happens to have zero real gaps today (its ~473-
    fund universe has been scored every month since inception, so union
    members simply shift rank rather than drop out of the scored set) —
    that's a property of this real data, not something to force. This test
    instead pins the type contract, which holds regardless of whether a
    given category's union currently has gaps.
    """
    r = client.get(f"/rankings/history?category={RANKING_CAT}&top_n=10&mode=union")
    data = r.json()
    assert len(data["series"]) > 0
    for s in data["series"]:
        for dp in s["data"]:
            assert dp["composite_score"] is None or isinstance(dp["composite_score"], float)


def test_ranking_history_insufficient_history_category_is_honest(client):
    """A taxonomy bucket that only ever existed under the new naming
    (e.g. Index Funds) genuinely has 1 real snapshot — must be reported
    as-is (1 date), never padded/fabricated to look like more history."""
    r = client.get("/rankings/history?category=Index Funds&top_n=10")
    assert r.status_code == 200
    data = r.json()
    assert len(data["dates"]) == 1, (
        f"Index Funds should have exactly 1 real snapshot, got: {data['dates']}"
    )


# ── 4. Full 35-value category taxonomy (category_taxonomy_current) ──────────

def test_taxonomy_has_expected_35_values(client):
    assert len(CATEGORY_TAXONOMY) == 35
    assert CATEGORY_TAXONOMY[0] == "ALL"
    assert set(CATEGORY_TAXONOMY[1:4]) == {"ALL Equity", "ALL Hybrid", "ALL Passive"}


def test_all_32_categories_accepted_without_erroring(client):
    """Every real taxonomy value must return 200 — including zero-coverage ones."""
    for cat in CATEGORY_TAXONOMY:
        r = client.get("/rankings/category", params={"category": cat})
        assert r.status_code == 200, f"category={cat!r} failed: {r.status_code} {r.text}"
        data = r.json()
        assert data["category"] == cat
        assert isinstance(data["results"], list)


def test_unknown_category_returns_400_not_500(client):
    r = client.get("/rankings/category?category=Not+A+Real+Category")
    assert r.status_code == 400


def test_categories_endpoint_lists_all_35_with_real_counts(client):
    r = client.get("/rankings/categories")
    assert r.status_code == 200
    data = r.json()
    assert len(data["categories"]) == 35
    keys = [c["key"] for c in data["categories"]]
    assert keys == CATEGORY_TAXONOMY
    for c in data["categories"]:
        assert isinstance(c["ranked_count"], int)
        assert c["ranked_count"] >= 0


def test_zero_coverage_category_returns_honest_empty_state(client):
    """
    Gold ETFs / Gold FoFs has real taxonomy schemes but none are in the
    rule-engine's scored universe (an equity/benchmark-relative model) —
    must be an honest empty list, not an error or fabricated rows.
    """
    r = client.get("/rankings/category", params={"category": "Gold ETFs / Gold FoFs"})
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 0
    assert data["results"] == []


def test_zero_coverage_category_with_aum_filter_still_honest_empty(client):
    """Step 3: AUM filter must compose cleanly with a zero-coverage category."""
    r = client.get("/rankings/category", params={"category": "Gold ETFs / Gold FoFs", "aum_min_cr": 1000})
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 0
    assert data["results"] == []


def test_aggregate_category_returns_real_union_of_leaves(client):
    """
    ALL Equity's total must equal the sum of its real per-leaf ranked counts,
    grouped by the actual bucket_group field returned by /rankings/categories
    (category_taxonomy_current's real grouping) — not a hand-picked list of
    "equity-sounding" category names.
    """
    cats = client.get("/rankings/categories").json()["categories"]
    equity_leaf_sum = sum(
        c["ranked_count"] for c in cats
        if not c["is_aggregate"] and c["bucket_group"] == "ALL Equity"
    )
    expected_total = next(c["ranked_count"] for c in cats if c["key"] == "ALL Equity")
    assert equity_leaf_sum == expected_total
    assert expected_total > 0

    r = client.get("/rankings/category", params={"category": "ALL Equity", "page_size": 1})
    assert r.status_code == 200
    assert r.json()["total"] == expected_total


def test_all_aggregate_equals_full_ranked_universe(client, db):
    """
    'ALL' must equal the true governed-pipeline universe — every schemecode
    with a real snapshot row under its current bucket_36 category — cross-
    checked directly against the DB, not a hardcoded count. This is
    strictly smaller than the full taxonomy (7,223 schemes) because
    recompute_all_rankings() requires ALL of the active rule version's
    components to be real for a fund (no fabricated neutral-percentile
    fallback for missing IR/TE data — see recompute.py's docstring).
    """
    from sqlalchemy import text as sqltext
    expected_total = db.execute(sqltext("""
        SELECT COUNT(DISTINCT s.schemecode)
        FROM selfmade_ranking_snapshot s
        JOIN category_taxonomy_current t
            ON t.schemecode = s.schemecode AND t.bucket_36 = s.category
    """)).scalar()
    assert expected_total > 0

    r = client.get("/rankings/category", params={"category": "ALL", "page_size": 1})
    assert r.status_code == 200
    assert r.json()["total"] == expected_total


# ── 5. Picker contract — FundPicker's "top 10 by default, search reaches
#      beyond 10" behavior is implemented entirely via this endpoint's
#      page_size/search params (no client-side truncation) ──────────────────

def test_picker_default_page_size_10_returns_top_10_by_rank(client):
    """FundPicker's no-search default request is page_size=10 — must return
    exactly 10 results (Large Cap has 170+ ranked funds), non-decreasing
    ranks starting at 1 (RANK() OVER ties mean the window isn't always a
    contiguous 1..10 — e.g. two funds tied at rank 6 push the next to 8)."""
    r = client.get(f"/rankings/category?category={RANKING_CAT}&page_size=10")
    data = r.json()
    assert data["total"] > 10
    results = data["results"]
    assert len(results) == 10
    ranks = [f["rank"] for f in results]
    assert ranks[0] == 1, f"First result should be rank 1, got: {ranks}"
    assert ranks == sorted(ranks), f"Ranks should be non-decreasing: {ranks}"


def test_picker_search_surfaces_fund_ranked_below_10th(client):
    """A fund ranked well outside the top 10 (rank 14, 'Kotak Large Cap Fund
    - Growth - Direct', schemecode 18629) must still be found when searching
    by name — this is what lets FundPicker reach beyond its top-10 default."""
    r = client.get(
        f"/rankings/category?category={RANKING_CAT}&page_size=10&search=Growth+-+Direct"
    )
    data = r.json()
    matched = {f["schemecode"]: f for f in data["results"]}
    assert 18629 in matched, (
        f"Expected schemecode 18629 in search results, got: {list(matched.keys())}"
    )
    assert matched[18629]["rank"] > 10, "Fixture assumption broken: fund should rank below 10th"


# ── 6. Frontend/backend taxonomy contract ────────────────────────────────────
# Regression (found 2026-07-20): Compare's fund picker hardcoded pre-migration
# legacy category labels ("Equity — Large Cap") that no longer matched the
# bucket_36 taxonomy after it was tightened to 35 real values, so every
# category selection in the picker 400'd. This test encodes the contract
# directly so a future taxonomy rename catches frontend/compare/index.tsx's
# PICKER_CATEGORIES going stale again.

FRONTEND_PICKER_CATEGORIES = ["Large Cap", "Mid Cap", "Small Cap"]


def test_frontend_picker_categories_are_valid_taxonomy_values(client):
    """Every category Compare's FundPicker hardcodes must be a real,
    currently-accepted /rankings/category value."""
    for cat in FRONTEND_PICKER_CATEGORIES:
        assert cat in CATEGORY_TAXONOMY, (
            f"'{cat}' (hardcoded in compare/index.tsx's PICKER_CATEGORIES) is not "
            f"a real taxonomy value — the picker's category dropdown would 400."
        )
        r = client.get("/rankings/category", params={"category": cat, "page_size": 1})
        assert r.status_code == 200, f"category={cat!r} failed: {r.status_code} {r.text}"


def test_all_hybrid_is_genuinely_zero_today(client):
    """
    Step 0/2 finding: the rule engine has never scored a Hybrid fund — every
    ALL Hybrid leaf (Arbitrage, Aggressive Hybrid, etc.) is real taxonomy
    with zero ranked coverage. Confirms this is a real data gap, not a bug.
    """
    r = client.get("/rankings/category", params={"category": "ALL Hybrid"})
    assert r.status_code == 200
    assert r.json()["total"] == 0
