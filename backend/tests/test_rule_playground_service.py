"""Unit tests for app.services.rule_playground.build_universe_sql.

All tests are pure string/dict assertions — no DB, no IO.
Each test verifies that a specific FilterParams combination produces
the expected WHERE clause fragment(s), JOIN additions, and params.
"""

from app.services.rule_playground import FilterParams, FilterSQL, build_universe_sql


# ── helpers ───────────────────────────────────────────────────────────────────

def _has_clause(sql: FilterSQL, fragment: str) -> bool:
    return any(fragment in clause for clause in sql.where_clauses)


def _has_join(sql: FilterSQL, fragment: str) -> bool:
    return fragment in sql.extra_joins


def _has_cte(sql: FilterSQL, fragment: str) -> bool:
    return any(fragment in cte for cte in sql.ctes)


def _has_warning(sql: FilterSQL, fragment: str) -> bool:
    return any(fragment in w for w in sql.warnings)


# ── no filters → empty result ─────────────────────────────────────────────────

def test_empty_filters_produce_status_clause_only():
    # exclude_merged=False so no table joins are triggered
    sql = build_universe_sql(FilterParams(exclude_merged=False))
    assert _has_clause(sql, "sm.status = :status")
    assert sql.params["status"] == "Active"
    assert sql.extra_joins == ""


def test_default_exclude_merged_joins_afd():
    # Default FilterParams has exclude_merged=True, so afd is always joined
    sql = build_universe_sql(FilterParams())
    assert _has_join(sql, "accord_fintech_scheme_details afd")


# ── Eligibility ───────────────────────────────────────────────────────────────

def test_category_filter():
    sql = build_universe_sql(FilterParams(category="Large Cap Fund"))
    assert _has_clause(sql, "sm.category = :category")
    assert sql.params["category"] == "Large Cap Fund"


def test_bucket_36_overrides_category():
    sql = build_universe_sql(FilterParams(category="Large Cap Fund", bucket_36="Large Cap"))
    assert _has_clause(sql, "ctc.bucket_36 = :bucket_36")
    assert sql.params["bucket_36"] == "Large Cap"
    # raw category clause must NOT be present when bucket_36 is set
    assert not _has_clause(sql, "sm.category = :category")


def test_amc_codes_single():
    sql = build_universe_sql(FilterParams(amc_codes=[400004]))
    assert _has_join(sql, "amc_mst_new amn ON amn.amc_code::text = sm.amc")
    assert _has_clause(sql, "amn.amc_code IN (:amc_0)")
    assert sql.params["amc_0"] == 400004


def test_amc_codes_multiple():
    sql = build_universe_sql(FilterParams(amc_codes=[400004, 400013]))
    assert _has_clause(sql, ":amc_0")
    assert _has_clause(sql, ":amc_1")
    assert sql.params["amc_1"] == 400013


def test_status_override():
    sql = build_universe_sql(FilterParams(status="Liquidated"))
    assert sql.params["status"] == "Liquidated"


def test_aum_range():
    sql = build_universe_sql(FilterParams(aum_min_cr=500, aum_max_cr=10000))
    assert _has_clause(sql, ">= :aum_min")
    assert _has_clause(sql, "<= :aum_max")
    assert sql.params["aum_min"] == 500.0
    assert sql.params["aum_max"] == 10000.0


def test_min_history_joins_afd():
    sql = build_universe_sql(FilterParams(min_history_years=3.0))
    assert _has_join(sql, "accord_fintech_scheme_details afd")
    assert _has_clause(sql, "afd.incept_date")
    assert sql.params["hist_interval"] == 3.0


def test_expense_ratio_max_creates_cte():
    sql = build_universe_sql(FilterParams(expense_ratio_max=1.5))
    assert _has_cte(sql, "latest_er AS")
    assert _has_join(sql, "latest_er ler")
    assert _has_clause(sql, "ler.expratio <= :er_max")
    assert sql.params["er_max"] == 1.5


def test_exclude_merged_joins_afd():
    sql = build_universe_sql(FilterParams(exclude_merged=True))
    assert _has_join(sql, "accord_fintech_scheme_details afd")
    assert _has_clause(sql, "afd.status != 'Merged'")


def test_exclude_merged_false_omits_clause():
    sql = build_universe_sql(FilterParams(exclude_merged=False))
    assert not _has_clause(sql, "Merged")


# ── Data Quality ──────────────────────────────────────────────────────────────

def test_require_benchmark_mapped():
    sql = build_universe_sql(FilterParams(require_benchmark_mapped=True))
    assert _has_clause(sql, "selfmade_scheme_category_benchmark")
    assert _has_clause(sql, "is_fallback_benchmark")


def test_holdings_freshness_creates_cte():
    sql = build_universe_sql(FilterParams(holdings_freshness_max_months=6))
    assert _has_cte(sql, "holdings_freshness AS")
    assert _has_join(sql, "holdings_freshness hf")
    assert sql.params["hf_max"] == 6


def test_data_confidence_high():
    sql = build_universe_sql(FilterParams(data_confidence_min="High"))
    assert _has_clause(sql, ">= :dc_min")
    assert sql.params["dc_min"] == 70.0


def test_data_confidence_medium():
    sql = build_universe_sql(FilterParams(data_confidence_min="Medium"))
    assert sql.params["dc_min"] == 40.0


def test_nav_coverage_is_stubbed():
    sql = build_universe_sql(FilterParams(nav_coverage_pct_min=80.0))
    assert _has_warning(sql, "nav_coverage filter skipped")
    # must NOT add any WHERE clause (stub = no-op filter)
    assert not _has_clause(sql, "nav")


# ── Structural Improvement ────────────────────────────────────────────────────

def test_ir_percentile_min():
    sql = build_universe_sql(FilterParams(ir_percentile_min=60.0))
    assert _has_join(sql, "selfmade_scheme_ranking sr")
    assert _has_clause(sql, "sr.pct_ir_3yr >= :ir_pct_min")
    assert sql.params["ir_pct_min"] == 60.0


def test_outperformance_majority():
    sql = build_universe_sql(FilterParams(outperformance_ratio_min=0.5))
    assert _has_join(sql, "selfmade_scheme_metrics smm")
    # Must require at least 2/3 periods
    assert _has_clause(sql, ">= 2")


def test_outperformance_all():
    sql = build_universe_sql(FilterParams(outperformance_ratio_min=1.0))
    assert _has_clause(sql, "outperformed_1yr AND smm.outperformed_3yr AND smm.outperformed_5yr")


def test_rank_movement_is_stubbed():
    sql = build_universe_sql(FilterParams(rank_movement_min=3))
    assert _has_warning(sql, "rank_movement filter skipped")


def test_improvement_metric_is_stubbed():
    sql = build_universe_sql(FilterParams(improvement_metric_min=0.5))
    assert _has_warning(sql, "improvement_metric filter skipped")


# ── Risk ──────────────────────────────────────────────────────────────────────

def test_tracking_error_max():
    sql = build_universe_sql(FilterParams(tracking_error_max=8.0))
    assert _has_join(sql, "selfmade_scheme_metrics smm")
    assert _has_clause(sql, "smm.tracking_error_3yr <= :te_max")
    assert sql.params["te_max"] == 8.0


def test_volatility_is_stubbed():
    sql = build_universe_sql(FilterParams(volatility_max=20.0))
    assert _has_warning(sql, "volatility filter skipped")


def test_downside_capture_is_stubbed():
    sql = build_universe_sql(FilterParams(downside_capture_max=90.0))
    assert _has_warning(sql, "downside_capture filter skipped")


# ── Portfolio ─────────────────────────────────────────────────────────────────

def test_holding_concentration_max():
    sql = build_universe_sql(FilterParams(holding_concentration_max=30.0))
    assert _has_cte(sql, "top5_conc AS")
    assert _has_join(sql, "top5_conc tc")
    assert _has_clause(sql, "tc.top5_pct <= :conc_max")
    assert sql.params["conc_max"] == 30.0


def test_sector_exposure():
    sql = build_universe_sql(FilterParams(sector_exposure={"Financial Services": 20.0}))
    assert _has_cte(sql, "sector_exp_0 AS")
    assert sql.params["sector_0"] == "Financial Services"
    assert sql.params["sector_pct_0"] == 20.0


# ── Plan / Option ─────────────────────────────────────────────────────────────

def test_plan_type_direct():
    sql = build_universe_sql(FilterParams(plan_type="direct"))
    assert _has_join(sql, "accord_fintech_scheme_details afd")
    assert _has_clause(sql, "afd.optiontype LIKE 'D%'")


def test_option_type_idcw():
    sql = build_universe_sql(FilterParams(option_type="idcw"))
    assert _has_clause(sql, "defaultplan")


# ── Stubs: asset alloc / change history ──────────────────────────────────────

def test_cash_exposure_is_stubbed():
    sql = build_universe_sql(FilterParams(cash_exposure_max=5.0))
    assert _has_warning(sql, "cash_exposure_max")


def test_change_history_stubs():
    sql = build_universe_sql(FilterParams(
        exclude_category_changed_since_version=2,
        exclude_benchmark_changed_since_version=1,
    ))
    assert _has_warning(sql, "exclude_category_changed_since_version")
    assert _has_warning(sql, "exclude_benchmark_changed_since_version")


# ── Multiple filters compose cleanly ─────────────────────────────────────────

def test_combined_filters_no_duplicate_joins():
    sql = build_universe_sql(FilterParams(
        exclude_merged=True,
        min_history_years=2.0,
        plan_type="direct",
    ))
    # afd should be joined exactly once even though 3 filters need it
    assert sql.extra_joins.count("accord_fintech_scheme_details afd") == 1


def test_combined_filters_params_do_not_collide():
    sql = build_universe_sql(FilterParams(
        aum_min_cr=100,
        expense_ratio_max=2.0,
        tracking_error_max=10.0,
        holding_concentration_max=35.0,
    ))
    assert "aum_min" in sql.params
    assert "er_max" in sql.params
    assert "te_max" in sql.params
    assert "conc_max" in sql.params
    # All distinct, no collisions
    assert len(sql.params) == len(set(sql.params))
