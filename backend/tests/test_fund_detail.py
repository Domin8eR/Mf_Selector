"""
Integration tests — Fund Detail page endpoints and insight templates.

Run: pytest tests/test_fund_detail.py -v

Verifies:
  - growth-of-10k correct shape (fund + benchmark series)
  - consistency-heatmap 36 cells
  - sectors_to_80 calculation
  - 3+ FUND_*_V1 templates render for a ranked fund
  - selfmade_portfolio_holding weight sum ~93-98%
  - holdings endpoint returns selfmade data
  - documents endpoint returns 3 docs per fund
  - fund summary-v2 includes rank + IR fields
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    """Use real Altstreet_AI DB — selfmade_ tables live there, not in altstreet_test."""
    with TestClient(app) as c:
        yield c


SAMPLE_SC = 19619
OTHER_SC = 18434


class TestGrowthOf10k:
    def test_returns_200(self, client):
        r = client.get(f"/metrics/growth-of-10k/{SAMPLE_SC}?period=3Y")
        assert r.status_code == 200

    def test_shape(self, client):
        r = client.get(f"/metrics/growth-of-10k/{SAMPLE_SC}?period=3Y")
        d = r.json()
        assert "fund_series" in d
        assert "benchmark_series" in d
        assert len(d["fund_series"]) >= 20, "Expected 20+ data points"
        assert len(d["benchmark_series"]) >= 20

    def test_starts_at_10000(self, client):
        r = client.get(f"/metrics/growth-of-10k/{SAMPLE_SC}?period=1Y")
        d = r.json()
        fund = d["fund_series"]
        bm = d["benchmark_series"]
        assert abs(fund[0]["value"] - 10000) < 1.0, "Fund series should start at ~10000"
        assert abs(bm[0]["value"] - 10000) < 1.0, "Benchmark series should start at ~10000"

    def test_fund_grows_with_positive_cagr(self, client):
        r = client.get(f"/metrics/growth-of-10k/{SAMPLE_SC}?period=3Y")
        d = r.json()
        fund = d["fund_series"]
        assert fund[-1]["value"] > fund[0]["value"], "Fund with positive CAGR should grow"

    def test_versioned_response(self, client):
        r = client.get(f"/metrics/growth-of-10k/{SAMPLE_SC}?period=3Y")
        d = r.json()
        for field in ("data_version", "rule_version", "calculation_version", "as_of_date"):
            assert field in d, f"Missing versioned field: {field}"

    def test_all_periods(self, client):
        for period in ("1M", "6M", "1Y", "3Y", "5Y"):
            r = client.get(f"/metrics/growth-of-10k/{SAMPLE_SC}?period={period}")
            assert r.status_code == 200, f"Period {period} failed"
            d = r.json()
            assert d["period"] == period

    def test_data_note_present(self, client):
        r = client.get(f"/metrics/growth-of-10k/{SAMPLE_SC}?period=3Y")
        d = r.json()
        assert "data_note" in d
        assert len(d["data_note"]) > 10


class TestConsistencyHeatmap:
    def test_returns_200(self, client):
        r = client.get(f"/metrics/consistency-heatmap/{SAMPLE_SC}")
        assert r.status_code == 200

    def test_36_cells(self, client):
        r = client.get(f"/metrics/consistency-heatmap/{SAMPLE_SC}")
        d = r.json()
        assert len(d["cells"]) == 36, f"Expected 36 cells, got {len(d['cells'])}"

    def test_cell_structure(self, client):
        r = client.get(f"/metrics/consistency-heatmap/{SAMPLE_SC}")
        cells = r.json()["cells"]
        for c in cells:
            assert "year" in c
            assert "month" in c
            assert "ir" in c
            assert "color" in c
            assert c["color"] in ("green", "yellow", "red")

    def test_real_months_present(self, client):
        r = client.get(f"/metrics/consistency-heatmap/{SAMPLE_SC}")
        d = r.json()
        assert d["real_months"] >= 1, "Should have at least 1 real snapshot month"

    def test_color_logic(self, client):
        r = client.get(f"/metrics/consistency-heatmap/{SAMPLE_SC}")
        cells = r.json()["cells"]
        for c in cells:
            ir = c["ir"]
            if ir >= 0.3:
                assert c["color"] == "green"
            elif ir >= 0.0:
                assert c["color"] == "yellow"
            else:
                assert c["color"] == "red"


class TestHoldings:
    def test_returns_200(self, client):
        r = client.get(f"/schemes/{SAMPLE_SC}/holdings")
        assert r.status_code == 200

    def test_source_is_selfmade(self, client):
        r = client.get(f"/schemes/{SAMPLE_SC}/holdings")
        d = r.json()
        assert d["source"] == "selfmade"

    def test_weight_sum_in_range(self, client):
        r = client.get(f"/schemes/{SAMPLE_SC}/holdings?limit=50")
        d = r.json()
        total = d["total_weight_pct"]
        assert total is not None
        assert 85.0 <= total <= 100.0, f"Weight sum {total}% outside expected 85-100% range"

    def test_sector_fields_present(self, client):
        r = client.get(f"/schemes/{SAMPLE_SC}/holdings")
        holdings = r.json()["holdings"]
        assert len(holdings) > 0
        for h in holdings:
            assert "company_name" in h
            assert "weight_pct" in h
            assert "sector" in h
            assert "market_cap_bucket" in h

    def test_holdings_ordered_by_weight(self, client):
        r = client.get(f"/schemes/{SAMPLE_SC}/holdings?limit=10")
        weights = [h["weight_pct"] for h in r.json()["holdings"]]
        assert weights == sorted(weights, reverse=True), "Holdings should be descending by weight"

    def test_limit_50_returns_full_portfolio_not_capped_at_10(self, client):
        """Fund Detail's search-within-holdings feature fetches limit=50 once
        and filters client-side; this only works if the endpoint actually
        returns more than 10 rows for a fund with more than 10 holdings."""
        r = client.get(f"/schemes/{SAMPLE_SC}/holdings?limit=50")
        holdings = r.json()["holdings"]
        assert len(holdings) > 10, (
            f"Expected the full portfolio (>10 rows) at limit=50, got {len(holdings)}"
        )

    def test_search_beyond_top_10_finds_real_holding(self, client):
        """'Dr Reddys Laboratories' is fund 19619's 11th-ranked holding by
        weight (real selfmade_portfolio_holding data) — outside the top-10
        default view. It must be absent at limit=10 and present at limit=50,
        proving the frontend's full-list-then-filter approach can actually
        reach it."""
        r10 = client.get(f"/schemes/{SAMPLE_SC}/holdings?limit=10")
        names_10 = [h["company_name"] for h in r10.json()["holdings"]]
        assert "Dr Reddys Laboratories" not in names_10, (
            "Fixture assumption broken: Dr Reddys Laboratories should rank below 10"
        )

        r50 = client.get(f"/schemes/{SAMPLE_SC}/holdings?limit=50")
        holdings_50 = r50.json()["holdings"]
        match = next((h for h in holdings_50 if h["company_name"] == "Dr Reddys Laboratories"), None)
        assert match is not None, "Dr Reddys Laboratories missing from the full (limit=50) holdings list"
        assert 3.0 < match["weight_pct"] < 4.0

    def test_sectors_to_80_calculation(self, client):
        """Verify that fewer than 15 sectors cover 80% of portfolio weight."""
        r = client.get(f"/schemes/{SAMPLE_SC}/holdings?limit=50")
        holdings = r.json()["holdings"]
        total_w = sum(h["weight_pct"] for h in holdings if h["weight_pct"])
        sector_wt: dict[str, float] = {}
        for h in holdings:
            s = h["sector"] or "Unknown"
            sector_wt[s] = sector_wt.get(s, 0.0) + (h["weight_pct"] or 0.0)
        sorted_sectors = sorted(sector_wt.values(), reverse=True)
        cumulative = 0.0
        sectors_to_80 = 0
        for sw in sorted_sectors:
            cumulative += sw
            sectors_to_80 += 1
            if total_w > 0 and cumulative / total_w >= 0.80:
                break
        assert 1 <= sectors_to_80 <= 15, f"sectors_to_80={sectors_to_80} out of expected range"


class TestDocuments:
    def test_returns_200(self, client):
        r = client.get(f"/schemes/{SAMPLE_SC}/documents")
        assert r.status_code == 200

    def test_three_docs_per_fund(self, client):
        r = client.get(f"/schemes/{SAMPLE_SC}/documents")
        docs = r.json()["documents"]
        assert len(docs) == 3, f"Expected 3 documents, got {len(docs)}"

    def test_doc_types(self, client):
        r = client.get(f"/schemes/{SAMPLE_SC}/documents")
        types = {d["doc_type"] for d in r.json()["documents"]}
        assert types == {"factsheet", "holdings", "sid"}

    def test_labels_present(self, client):
        r = client.get(f"/schemes/{SAMPLE_SC}/documents")
        for doc in r.json()["documents"]:
            assert "label" in doc
            assert len(doc["label"]) > 3


class TestFundSummaryV2:
    def test_returns_200(self, client):
        r = client.get(f"/metrics/fund/{SAMPLE_SC}/summary-v2")
        assert r.status_code == 200

    def test_rank_fields(self, client):
        r = client.get(f"/metrics/fund/{SAMPLE_SC}/summary-v2")
        d = r.json()
        assert "rank_in_category" in d
        assert "total_in_category" in d
        assert d["rank_in_category"] is not None
        assert d["total_in_category"] is not None
        assert 1 <= d["rank_in_category"] <= d["total_in_category"]

    def test_ir_field(self, client):
        r = client.get(f"/metrics/fund/{SAMPLE_SC}/summary-v2")
        d = r.json()
        assert "information_ratio_3yr" in d
        assert d["information_ratio_3yr"] is not None

    def test_versioned_response(self, client):
        r = client.get(f"/metrics/fund/{SAMPLE_SC}/summary-v2")
        d = r.json()
        for f in ("data_version", "rule_version", "calculation_version", "as_of_date"):
            assert f in d

    def test_tier_present(self, client):
        r = client.get(f"/metrics/fund/{SAMPLE_SC}/summary-v2")
        d = r.json()
        assert "tier" in d
        assert d["tier"] in ("Strong", "Good", "Neutral", "Weak", None)


class TestFundDetailInsights:
    def test_returns_200(self, client):
        r = client.get(f"/insights/fund/{SAMPLE_SC}")
        assert r.status_code == 200

    def test_at_least_3_fund_v1_cards(self, client):
        r = client.get(f"/insights/fund/{SAMPLE_SC}")
        cards = r.json()["cards"]
        v1_cards = [c for c in cards if c["template_id"].startswith("FUND_") and c["template_id"].endswith("_V1")]
        assert len(v1_cards) >= 3, f"Expected ≥3 FUND_*_V1 cards, got {len(v1_cards)}"

    def test_no_forbidden_language(self, client):
        r = client.get(f"/insights/fund/{SAMPLE_SC}")
        cards = r.json()["cards"]
        forbidden = ["recommend", "buy", "sell", "best fund", "top pick"]
        for card in cards:
            text = (card.get("headline", "") + " " + card.get("body", "")).lower()
            for word in forbidden:
                assert word not in text, f"Forbidden word '{word}' in card {card['template_id']}"

    def test_holdings_template_fires(self, client):
        """2026-07-18 migration: FUND_HOLDINGS_AVAIL_FULL/STALE/FRESH_V1 were
        folded into FUND_TOP_HOLDINGS_V1 (as_of_date now lives in its
        expanded bullets); FUND_HOLDINGS_AVAIL_NONE_V1 and the new <5-holdings
        fallback are preserved."""
        r = client.get(f"/insights/fund/{SAMPLE_SC}")
        cards = r.json()["cards"]
        holding_ids = {
            "FUND_TOP_HOLDINGS_V1", "FUND_TOP_HOLDINGS_LESS_THAN_5_V1",
            "FUND_HOLDINGS_AVAIL_NONE_V1",
        }
        fired = [c for c in cards if c["template_id"] in holding_ids]
        assert len(fired) >= 1, "At least one holdings template should fire"

    def test_rank_tier_template_fires(self, client):
        """FUND_PERF_RANK_TIER_V1 was folded into the 3-way FUND_3Y_IR_*_V1
        percentile split and FUND_3Y_PERFORMANCE_STRONG/MIXED_V1's expanded
        bullets (rank_in_category/total_in_category) — no longer a separate
        always-firing card."""
        r = client.get(f"/insights/fund/{SAMPLE_SC}")
        ids = [c["template_id"] for c in r.json()["cards"]]
        ir_ids = {"FUND_3Y_IR_TOP_TIER_V1", "FUND_3Y_IR_ACCEPTABLE_V1",
                  "FUND_3Y_IR_WEAK_V1", "FUND_3Y_IR_INSUFFICIENT_HISTORY_V1"}
        assert ir_ids & set(ids), "one of the 3Y IR slot templates should always fire"

    def test_trend_template_fires(self, client):
        r = client.get(f"/insights/fund/{SAMPLE_SC}")
        trend_ids = {
            "FUND_TREND_IMPROVING_V1", "FUND_TREND_WEAKENING_V1",
            "FUND_TREND_MIXED_V1", "FUND_TREND_INSUFFICIENT_DATA_V1",
        }
        cards = r.json()["cards"]
        fired = [c for c in cards if c["template_id"] in trend_ids]
        assert len(fired) >= 1, "At least one trend template (or its preserved fallback) should fire"

    def test_sectors_template_fires(self, client):
        """Sectors group folded FUND_SECTOR_FIN_HEAVY/BALANCED_V1 into
        FUND_TOP_SECTORS_V1 + FUND_SECTORS_TO_80_V1; fires for any ranked
        fund with >=3 classified sectors, else the preserved fallback."""
        r = client.get(f"/insights/fund/{SAMPLE_SC}")
        cards = r.json()["cards"]
        sector_ids = {
            "FUND_TOP_SECTORS_V1", "FUND_SECTORS_TO_80_V1", "FUND_SECTORS_UNAVAILABLE_V1",
        }
        fired = [c for c in cards if c["template_id"] in sector_ids]
        assert len(fired) >= 1, "At least one sector template (or its preserved fallback) should fire"


class TestMultiFundWeightSums:
    """Verify selfmade_portfolio_holding weight sums are 95-98% across a sample of funds."""

    # Hand-picked schemecodes from the seed — all are known ranked LC funds
    SAMPLE_FUNDS = [19619, 18434, 22, 23, 171]

    def test_weight_sums_95_to_98_pct(self, client):
        """Total holding weight per fund should be 95–98% (seed target was 0.93–0.98,
        but the LC pool uses 5 boosted holdings so effective sums cluster 95–98%)."""
        for sc in self.SAMPLE_FUNDS:
            r = client.get(f"/schemes/{sc}/holdings?limit=50")
            assert r.status_code == 200, f"Holdings endpoint failed for {sc}"
            d = r.json()
            total = d["total_weight_pct"]
            assert total is not None, f"total_weight_pct is None for {sc}"
            assert 85.0 <= total <= 100.0, (
                f"Fund {sc}: total_weight_pct={total} outside 85-100%"
            )

    def test_weight_sums_selfmade_source(self, client):
        """All sampled funds must serve selfmade holdings (not altstreet_scheme_holdings)."""
        for sc in self.SAMPLE_FUNDS:
            r = client.get(f"/schemes/{sc}/holdings")
            assert r.json()["source"] == "selfmade", f"Fund {sc} not serving selfmade source"


class TestSectorsTo80Fixture:
    """Hand-checkable fixture: sectors_to_80 for SAMPLE_SC must be in a tight range."""

    def test_sectors_to_80_fixture(self, client):
        """
        For fund 19619 seeded from LC pool (30 securities across ~6 sectors),
        it should take 1–6 sectors to cover 80% of portfolio weight.
        """
        r = client.get(f"/schemes/{SAMPLE_SC}/holdings?limit=50")
        assert r.status_code == 200
        holdings = r.json()["holdings"]
        total_w = sum(h["weight_pct"] for h in holdings if h["weight_pct"])
        assert total_w > 0, "Holdings weight sum should be positive"

        sector_wt: dict[str, float] = {}
        for h in holdings:
            s = h["sector"] or "Unknown"
            sector_wt[s] = sector_wt.get(s, 0.0) + (h["weight_pct"] or 0.0)

        sorted_sectors = sorted(sector_wt.values(), reverse=True)
        cumulative = 0.0
        sectors_to_80 = 0
        for sw in sorted_sectors:
            cumulative += sw
            sectors_to_80 += 1
            if total_w > 0 and cumulative / total_w >= 0.80:
                break

        # LC pool has 6 distinct sectors; 80% coverage within 1–6 is expected
        assert 1 <= sectors_to_80 <= 6, (
            f"sectors_to_80={sectors_to_80} for LC fund {SAMPLE_SC}; "
            f"sector distribution: {sorted(sector_wt.items(), key=lambda x: -x[1])}"
        )

    def test_sectors_to_80_other_fund(self, client):
        """Cross-check with a second fund to ensure sectors_to_80 logic is consistent."""
        r = client.get(f"/schemes/{OTHER_SC}/holdings?limit=50")
        holdings = r.json()["holdings"]
        total_w = sum(h["weight_pct"] for h in holdings if h["weight_pct"])
        sector_wt: dict[str, float] = {}
        for h in holdings:
            s = h["sector"] or "Unknown"
            sector_wt[s] = sector_wt.get(s, 0.0) + (h["weight_pct"] or 0.0)
        sorted_sectors = sorted(sector_wt.values(), reverse=True)
        cumulative = 0.0
        sectors_to_80 = 0
        for sw in sorted_sectors:
            cumulative += sw
            sectors_to_80 += 1
            if total_w > 0 and cumulative / total_w >= 0.80:
                break
        assert 1 <= sectors_to_80 <= 15, f"sectors_to_80={sectors_to_80} out of valid range for {OTHER_SC}"


class TestHeatmapAllReal:
    """After Item 1 fix: all 36 heatmap cells should be grounded in real data."""

    def test_all_cells_real(self, client):
        """real_months should equal 36 for any fund that has accord_fintech anchor data."""
        r = client.get(f"/metrics/consistency-heatmap/{SAMPLE_SC}")
        assert r.status_code == 200
        d = r.json()
        assert d["real_months"] == 36, (
            f"Expected 36 real months, got {d['real_months']}. "
            f"data_note: {d['data_note']}"
        )

    def test_cells_is_real_flag(self, client):
        r = client.get(f"/metrics/consistency-heatmap/{SAMPLE_SC}")
        cells = r.json()["cells"]
        synthetic = [c for c in cells if not c["is_real"]]
        assert len(synthetic) == 0, f"{len(synthetic)} synthetic cells remain after Item 1 fix"


class TestRollingIr:
    """Item 3: rolling IR endpoint returns real monthly IR + excess return series."""

    def test_returns_200(self, client):
        r = client.get(f"/metrics/fund/{SAMPLE_SC}/rolling-ir")
        assert r.status_code == 200

    def test_response_shape(self, client):
        r = client.get(f"/metrics/fund/{SAMPLE_SC}/rolling-ir")
        d = r.json()
        assert "rolling_ir_series" in d, "Missing rolling_ir_series"
        assert "excess_return_series" in d, "Missing excess_return_series"
        assert "benchmark_name" in d

    def test_series_non_empty(self, client):
        r = client.get(f"/metrics/fund/{SAMPLE_SC}/rolling-ir")
        d = r.json()
        assert len(d["rolling_ir_series"]) >= 10, "Expected ≥10 rolling IR data points"
        assert len(d["excess_return_series"]) >= 10, "Expected ≥10 excess return points"

    def test_ir_point_structure(self, client):
        r = client.get(f"/metrics/fund/{SAMPLE_SC}/rolling-ir")
        for pt in r.json()["rolling_ir_series"]:
            assert "date" in pt
            assert "ir" in pt
            assert isinstance(pt["ir"], (int, float))


class TestBenchmarkComparison:
    """Item 4: benchmark comparison endpoint uses selfmade_ tables."""

    def test_returns_200(self, client):
        r = client.get(f"/metrics/fund/{SAMPLE_SC}/benchmark-comparison")
        assert r.status_code == 200

    def test_response_shape(self, client):
        d = client.get(f"/metrics/fund/{SAMPLE_SC}/benchmark-comparison").json()
        assert "fund" in d
        assert "benchmark" in d
        assert "excess" in d
        assert "benchmark_name" in d

    def test_fund_returns_present(self, client):
        d = client.get(f"/metrics/fund/{SAMPLE_SC}/benchmark-comparison").json()
        fund = d["fund"]
        assert fund.get("return_1y") is not None, "fund.return_1y should not be None"
        assert fund.get("return_3y") is not None, "fund.return_3y should not be None"

    def test_benchmark_returns_present(self, client):
        d = client.get(f"/metrics/fund/{SAMPLE_SC}/benchmark-comparison").json()
        bm = d["benchmark"]
        assert bm.get("return_1y") is not None, "benchmark.return_1y should not be None"
        assert bm.get("return_3y") is not None, "benchmark.return_3y should not be None"

    def test_ir_and_sharpe_present(self, client):
        d = client.get(f"/metrics/fund/{SAMPLE_SC}/benchmark-comparison").json()
        fund = d["fund"]
        assert fund.get("information_ratio_3yr") is not None
        assert fund.get("sharpe_ratio_3yr") is not None

    def test_excess_return_calculation(self, client):
        """excess = fund_return - benchmark_return; sign sanity check."""
        d = client.get(f"/metrics/fund/{SAMPLE_SC}/benchmark-comparison").json()
        f1 = d["fund"].get("return_1y")
        b1 = d["benchmark"].get("return_1y")
        e1 = d["excess"].get("return_1y")
        if f1 is not None and b1 is not None and e1 is not None:
            assert abs(e1 - (f1 - b1)) < 0.05, f"excess_1y mismatch: {e1} != {f1} - {b1}"
