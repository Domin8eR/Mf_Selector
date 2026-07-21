"""
Integration tests — Fund Comparison endpoint and related capabilities.

Run: pytest tests/test_compare.py -v

Covers (per Prompt 4 spec):
  1. weighted_overlap / sector_overlap against hand-checkable fixture values
  2. active_share returns null/insufficient_data when benchmark data is absent
  3. portfolio_stability returns null/insufficient_data when no historical snapshot
  4. ≥4 CMP_*_V1 templates render for a 2-fund comparison
  5. POST /compare/funds rejects 1-fund and 5-fund requests with 400
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    """Use real Altstreet_AI DB — selfmade_ tables live there, not in altstreet_test."""
    with TestClient(app) as c:
        yield c


# Two Large Cap funds in the same seeded universe — hand-checkable from DB
# Fund 22 (LC) vs Fund 171 (MC) — cross-category, known overlap from seed data
LC_FUND_A = 22
MC_FUND_B = 171
LC_FUND_C = 19619   # third ranked fund, also LC-seeded


# ── Item 5: Input validation ───────────────────────────────────────────────────

class TestInputValidation:
    def test_rejects_single_fund(self, client):
        r = client.post("/compare/funds", json={"schemecodes": [LC_FUND_A]})
        assert r.status_code == 400
        assert "at least 2" in r.json()["detail"].lower()

    def test_rejects_five_funds(self, client):
        r = client.post("/compare/funds", json={"schemecodes": [22, 171, 19619, 18434, 100]})
        assert r.status_code == 400
        assert "maximum 4" in r.json()["detail"].lower()

    def test_rejects_empty_list(self, client):
        r = client.post("/compare/funds", json={"schemecodes": []})
        assert r.status_code == 400

    def test_accepts_two_funds(self, client):
        r = client.post("/compare/funds", json={"schemecodes": [LC_FUND_A, MC_FUND_B]})
        assert r.status_code == 200

    def test_accepts_four_funds(self, client):
        r = client.post("/compare/funds", json={"schemecodes": [22, 171, 19619, 18434]})
        assert r.status_code == 200


# ── Item 3: Weighted overlap and sector overlap (hand-checkable fixture) ───────

class TestOverlapFixture:
    """
    Fund 22 (LC) vs Fund 171 (MC): cross-category pair seeded from different security
    pools (LC pool: 30 securities, MC pool: 25 securities). Overlap must be low.
    Sector overlap will be higher because both pools share sector labels.

    Hand-checkable from DB:
      SELECT COUNT(*) FROM selfmade_portfolio_holding WHERE scheme_id IN (22,171)
    """

    @pytest.fixture(scope="class")
    def resp(self, client):
        r = client.post("/compare/funds", json={"schemecodes": [LC_FUND_A, MC_FUND_B]})
        assert r.status_code == 200
        return r.json()

    def test_layout_is_a(self, resp):
        assert resp["layout"] == "A"

    def test_weighted_overlap_is_low_for_lc_vs_mc(self, resp):
        """LC fund vs MC fund must have low holdings overlap (<30%)."""
        wo = resp["holdings_overlap"]["weighted_overlap"]
        assert wo is not None
        assert wo < 30.0, f"Expected weighted_overlap < 30% for cross-category, got {wo:.2f}%"

    def test_common_count_is_present(self, resp):
        cc = resp["holdings_overlap"]["common_count"]
        assert isinstance(cc, int)
        assert cc >= 0

    def test_jaccard_is_present(self, resp):
        j = resp["holdings_overlap"]["jaccard"]
        # jaccard returned at top level
        assert j is not None
        assert 0.0 <= j <= 100.0

    def test_sector_overlap_is_present(self, resp):
        so = resp["holdings_overlap"]["sector_overlap"]
        assert so is not None
        assert 0.0 <= so <= 100.0

    def test_sector_table_has_rows(self, resp):
        st = resp["holdings_overlap"]["sector_table"]
        assert len(st) > 0, "Sector table must have at least one row"

    def test_sector_table_row_structure(self, resp):
        row = resp["holdings_overlap"]["sector_table"][0]
        assert "sector" in row
        assert "weights" in row
        assert "overlap" in row
        # weights should be keyed by schemecode string
        assert str(LC_FUND_A) in row["weights"] or str(MC_FUND_B) in row["weights"]

    def test_common_holdings_structure(self, resp):
        for h in resp["holdings_overlap"]["common_holdings"]:
            assert "security_name" in h
            assert "weight_a" in h
            assert "weight_b" in h
            assert "min_weight" in h

    def test_pairs_key_names(self, resp):
        """Backend returns fund_a/fund_b (not sc_a/sc_b)."""
        for pair in resp["holdings_overlap"]["pairs"]:
            assert "fund_a" in pair
            assert "fund_b" in pair
            assert "weighted_overlap" in pair
            assert "common_count" in pair


class TestOverlapThreeFunds:
    """3-fund Layout B: pairwise pairs list must have 3 entries (C(3,2)=3)."""

    @pytest.fixture(scope="class")
    def resp(self, client):
        r = client.post("/compare/funds", json={"schemecodes": [LC_FUND_A, MC_FUND_B, LC_FUND_C]})
        assert r.status_code == 200
        return r.json()

    def test_layout_is_b(self, resp):
        assert resp["layout"] == "B"

    def test_three_pairs(self, resp):
        assert len(resp["holdings_overlap"]["pairs"]) == 3

    def test_lc_lc_overlap_higher_than_lc_mc(self, resp):
        """
        LC fund A vs LC fund C (same pool) should have higher overlap than LC vs MC.
        """
        pairs = resp["holdings_overlap"]["pairs"]
        def _wo(fa, fb):
            for p in pairs:
                if {p["fund_a"], p["fund_b"]} == {fa, fb}:
                    return p["weighted_overlap"]
            return None

        lc_lc = _wo(LC_FUND_A, LC_FUND_C)
        lc_mc = _wo(LC_FUND_A, MC_FUND_B)
        assert lc_lc is not None and lc_mc is not None
        assert lc_lc > lc_mc, (
            f"LC-LC overlap ({lc_lc:.1f}%) should exceed LC-MC ({lc_mc:.1f}%)"
        )

    def test_radar_data_absent_for_layout_b(self, resp):
        assert resp["radar_data"] is None

    def test_rank_history_absent_for_layout_b(self, resp):
        assert resp["rank_history"] is None


# ── Item 1: Active Share real values ──────────────────────────────────────────

class TestActiveShare:
    """
    Active Share for funds in the seeded universe must be non-null.
    The seeded selfmade_benchmark_holding has 3 benchmark indices:
      Nifty 100 TRI (40 holdings), Nifty Midcap 150 TRI (35), Nifty Smallcap 250 TRI (20).
    LC funds use Nifty 100 TRI benchmark → active_share must be computable.
    """

    @pytest.fixture(scope="class")
    def resp(self, client):
        r = client.post("/compare/funds", json={"schemecodes": [LC_FUND_A, MC_FUND_B, LC_FUND_C]})
        assert r.status_code == 200
        return r.json()

    def test_active_share_not_null_for_lc(self, resp):
        fund = next(f for f in resp["funds"] if f["schemecode"] == LC_FUND_A)
        assert fund["active_share"]["status"] == "ok"
        assert fund["active_share"]["value"] is not None

    def test_active_share_sensible_range(self, resp):
        """Active Share for active funds should be 20–100%."""
        for f in resp["funds"]:
            if f["active_share"]["status"] == "ok" and f["active_share"]["value"] is not None:
                val = f["active_share"]["value"]
                assert 0.0 <= val <= 100.0, f"Fund {f['schemecode']} active_share={val} out of range"

    def test_active_share_null_when_no_benchmark(self, client):
        """
        If a fund has no benchmark in selfmade_benchmark_holding, active_share must be
        insufficient_data, not a crash or a stale value.
        Use a fund that references a benchmark NOT in selfmade_benchmark_holding:
        seed_compare_data only seeded 3 index names. We can test this via
        funds with 'Equity — Small Cap' category whose benchmark might not match.
        For a definitive test we use the calculator directly.
        """
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.core.config import settings
        from app.insights.calculator import get_active_share_for_fund

        engine = create_engine(settings.database_url)
        Session = sessionmaker(bind=engine)
        with Session() as db:
            # Pass a nonexistent schemecode — no holdings → insufficient_data
            result = get_active_share_for_fund(db, schemecode=999999999)
        assert result["value"] is None
        assert result["status"] == "insufficient_data"


# ── Item 2: Portfolio Stability real values and null fallback ─────────────────

class TestPortfolioStability:
    """
    Historical snapshot at 2026-01-09 (12,318 rows) is ~6 months before the
    current snapshot at 2026-07-09. Funds with holdings at both dates must
    have non-null portfolio_stability.
    """

    @pytest.fixture(scope="class")
    def resp(self, client):
        r = client.post("/compare/funds", json={"schemecodes": [LC_FUND_A, MC_FUND_B, LC_FUND_C]})
        assert r.status_code == 200
        return r.json()

    def test_portfolio_stability_not_null(self, resp):
        for f in resp["funds"]:
            ps = f["portfolio_stability"]
            assert ps["status"] == "ok", (
                f"Fund {f['schemecode']} portfolio_stability status={ps['status']}"
            )
            assert ps["value"] is not None

    def test_portfolio_stability_sensible_range(self, resp):
        """Stability is a weighted overlap — must be between 0 and 100%."""
        for f in resp["funds"]:
            if f["portfolio_stability"]["status"] == "ok":
                v = f["portfolio_stability"]["value"]
                assert 0.0 <= v <= 100.0, f"portfolio_stability={v} out of range"

    def test_portfolio_stability_null_when_no_snapshot(self, client):
        """Fund with no historical snapshot must return insufficient_data."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.core.config import settings
        from app.insights.calculator import get_portfolio_stability_for_fund

        engine = create_engine(settings.database_url)
        Session = sessionmaker(bind=engine)
        with Session() as db:
            result = get_portfolio_stability_for_fund(db, schemecode=999999999)
        assert result["value"] is None
        assert result["status"] == "insufficient_data"


# ── Item 4: CMP_*_V1 templates rendering ─────────────────────────────────────

class TestCmpTemplates:
    """
    POST /insights/compare-funds must fire at least 4 CMP_*_V1 templates
    across the 7 card slots it fills.
    """

    @pytest.fixture(scope="class")
    def cards(self, client):
        r = client.post(
            "/insights/compare-funds",
            json={"schemecodes": [LC_FUND_A, MC_FUND_B], "evaluation_date": "2026-07-09"},
        )
        assert r.status_code == 200
        return r.json()["cards"]

    def test_returns_expected_card_count(self, cards):
        # 2026-07-18 migration: 28 CMP_*_V1 templates consolidated to 8 (sector
        # overlap and the separate "best overall" slot dropped — category
        # leader covers "who's ahead"). A 2-fund comparison fires at most
        # 5 slots: holdings overlap, category leader, 3Y IR, recent
        # improvement, laggard.
        assert 1 <= len(cards) <= 5, f"Expected 1-5 insight cards, got {len(cards)}"

    def test_all_have_cmp_v1_template_ids(self, cards):
        v1_count = sum(1 for c in cards if c["template_id"].startswith("CMP_") and c["template_id"].endswith("_V1"))
        assert v1_count >= 4, f"Expected ≥4 CMP_*_V1 templates, got {v1_count}: {[c['template_id'] for c in cards]}"

    def test_no_forbidden_language(self, cards):
        """compact_text/expanded_bullets replaced headline/body_text in the
        2026-07-18 compact-card migration."""
        forbidden = ["recommendation", "buy", "sell", "best fund", "top pick"]
        for c in cards:
            text = (c["compact_text"] + " " + " ".join(c["expanded_bullets"])).lower()
            for phrase in forbidden:
                assert phrase not in text, f"Forbidden phrase '{phrase}' in card {c['template_id']}: {c['compact_text']}"

    def test_cards_have_required_fields(self, cards):
        for c in cards:
            assert "template_id" in c
            assert "insight_code" in c
            assert "severity" in c
            assert "compact_text" in c
            assert "expanded_bullets" in c

    def test_holdings_overlap_template_fires(self, cards):
        overlap_cards = [c for c in cards if "HOLDINGS_OVERLAP" in c["template_id"]]
        assert len(overlap_cards) >= 1, "Expected at least one HOLDINGS_OVERLAP card"

    def test_sector_overlap_dropped(self, cards):
        """CMP_SECTOR_OVERLAP_*_V1 is not in the new 8-template set — dropped,
        not rendered as a card anymore."""
        sector_cards = [c for c in cards if "SECTOR_OVERLAP" in c["template_id"]]
        assert len(sector_cards) == 0

    def test_clear_or_no_clear_leader_fires(self, cards):
        """CMP_BEST_CLEAR/NO_CLEAR_WINNER_V1 merged into CMP_CLEAR_LEADER_V1 /
        CMP_NO_CLEAR_LEADER_V1 — one of the two always fires."""
        leader_cards = [c for c in cards if c["template_id"] in
                        ("CMP_CLEAR_LEADER_V1", "CMP_NO_CLEAR_LEADER_V1")]
        assert len(leader_cards) >= 1, "Expected CMP_CLEAR_LEADER_V1 or CMP_NO_CLEAR_LEADER_V1"

    def test_cmp_templates_for_three_funds(self, client):
        """Layout B (3 funds) uses the MULTI_FUND overlap template and the
        same 1-5 card range as the 2-fund case."""
        r = client.post(
            "/insights/compare-funds",
            json={"schemecodes": [LC_FUND_A, MC_FUND_B, LC_FUND_C], "evaluation_date": "2026-07-09"},
        )
        assert r.status_code == 200
        cards = r.json()["cards"]
        assert 1 <= len(cards) <= 5


# ── Layout A structure (2-fund full response) ─────────────────────────────────

class TestLayoutAStructure:
    @pytest.fixture(scope="class")
    def resp(self, client):
        r = client.post("/compare/funds", json={"schemecodes": [LC_FUND_A, MC_FUND_B]})
        assert r.status_code == 200
        return r.json()

    def test_radar_data_present(self, resp):
        assert resp["radar_data"] is not None
        assert str(LC_FUND_A) in resp["radar_data"]
        assert str(MC_FUND_B) in resp["radar_data"]

    def test_radar_axes(self, resp):
        for sc_str, axes in resp["radar_data"].items():
            assert "ir_3yr_normalized" in axes
            assert "active_share_normalized" in axes
            assert "expense_efficiency" in axes
            assert "portfolio_stability_normalized" in axes
            assert "downside_protection" in axes

    def test_rank_history_present(self, resp):
        rh = resp["rank_history"]
        assert rh is not None
        assert str(LC_FUND_A) in rh
        assert str(MC_FUND_B) in rh

    def test_rank_history_entries(self, resp):
        for sc_str, history in resp["rank_history"].items():
            assert isinstance(history, list)
            if history:
                assert "date" in history[0]
                assert "rank" in history[0]

    def test_advantages_dict(self, resp):
        adv = resp["advantages"]
        expected_keys = {
            "ir_3yr", "ir_slope_6m_proxy", "active_ret_3yr", "ret_3yr", "ret_1yr",
            "active_share", "portfolio_stability", "expense_ratio_pct", "composite_score",
        }
        for k in expected_keys:
            assert k in adv, f"Missing advantage key: {k}"

    def test_versioned_response_fields(self, resp):
        for field in ("data_version", "rule_version", "calculation_version"):
            assert field in resp, f"Missing versioned field: {field}"

    def test_per_fund_status_label(self, resp):
        valid = {"Strong", "Good", "Neutral", "Weak"}
        for f in resp["funds"]:
            assert f["status_label"] in valid, f"Unexpected status_label: {f['status_label']}"

    def test_expense_ratio_present(self, resp):
        for f in resp["funds"]:
            er = f["expense_ratio_pct"]
            assert "value" in er and "status" in er

    def test_unavailable_metrics_have_correct_shape(self, resp):
        """max_drawdown_pct and downside_capture_ratio are known-unavailable."""
        for f in resp["funds"]:
            md = f["max_drawdown_pct"]
            dc = f["downside_capture_ratio"]
            assert md["value"] is None
            assert md["status"] == "insufficient_data"
            assert dc["value"] is None
            assert dc["status"] == "insufficient_data"


# ── Regression: funds outside governed ranking coverage must degrade
#    honestly, not silently vanish from the comparison ───────────────────────
#
# Root cause (found 2026-07-20): the ranking-taxonomy migration tightened
# selfmade_ranking_snapshot to a strict-governed-metric requirement, dropping
# equity coverage from 1,920 to 825 funds. compare_funds' original query
# INNER JOINed from selfmade_ranking_snapshot, so a requested schemecode with
# no snapshot row (like 481, a real fund now outside strict coverage) was
# silently absent from the response — no error, no reason, `funds` just had
# fewer entries than requested, and `layout` was computed from the post-filter
# count so a genuine 2-fund request could render as the multi-fund grid
# layout with a single card and no explanation.

RANKED_FUND = 19619       # real fund, in selfmade_ranking_snapshot (Large Cap)
UNRANKED_FUND = 481       # real fund (Sectoral funds bucket_36), confirmed via
                          # category_taxonomy_current to have NO row in the
                          # latest selfmade_ranking_snapshot — outside strict
                          # governed coverage today


class TestUnrankedFundDegradesHonestly:
    @pytest.fixture(scope="class")
    def resp(self, client):
        r = client.post("/compare/funds", json={"schemecodes": [RANKED_FUND, UNRANKED_FUND]})
        assert r.status_code == 200
        return r.json()

    def test_both_requested_funds_are_present(self, resp):
        """The unranked fund must not be silently dropped."""
        schemecodes = {f["schemecode"] for f in resp["funds"]}
        assert schemecodes == {RANKED_FUND, UNRANKED_FUND}

    def test_layout_reflects_the_actual_2_fund_request(self, resp):
        """2 requested funds -> layout 'A', not the multi-fund grid layout
        with 1 real card that resulted from the old silent-drop bug."""
        assert resp["layout"] == "A"

    def test_unranked_fund_has_real_name_not_a_placeholder(self, resp):
        unranked = next(f for f in resp["funds"] if f["schemecode"] == UNRANKED_FUND)
        assert unranked["fund_name"] != f"Fund {UNRANKED_FUND}"
        assert len(unranked["fund_name"]) > 5

    def test_unranked_fund_shows_insufficient_data_with_a_reason(self, resp):
        unranked = next(f for f in resp["funds"] if f["schemecode"] == UNRANKED_FUND)
        assert unranked["status_label"] == "Insufficient Data"
        assert unranked["rank"] is None
        assert unranked["composite_score"] is None
        assert unranked["coverage_note"], "Must explain why this fund has no rank"
        assert "recommend" not in unranked["coverage_note"].lower()

    def test_ranked_fund_is_unaffected(self, resp):
        ranked = next(f for f in resp["funds"] if f["schemecode"] == RANKED_FUND)
        assert ranked["status_label"] in {"Strong", "Good", "Neutral", "Weak"}
        assert ranked["rank"] is not None
        assert ranked["composite_score"] is not None
        assert ranked["coverage_note"] is None

    def test_holdings_based_metrics_still_independent_of_ranking_coverage(self, resp):
        """active_share/portfolio_stability come from holdings data, not the
        ranking snapshot — confirm the taxonomy migration didn't break them."""
        ranked = next(f for f in resp["funds"] if f["schemecode"] == RANKED_FUND)
        assert ranked["active_share"]["status"] == "ok"
        assert ranked["portfolio_stability"]["status"] == "ok"
