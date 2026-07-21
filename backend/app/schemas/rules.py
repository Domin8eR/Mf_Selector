"""Pydantic schemas for rules endpoints."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.base import VersionedResponse


class EligibilityFilters(BaseModel):
    """
    Fund-universe eligibility filters for the V2 sandbox (POST /rules/sandbox/run-v2
    and /rules/sandbox/eligible-count) — defines WHICH funds a rule is scored
    against, separate from the rule's own metric weights.

    Every field here has REAL backing data as of the 2026-07 filter-catalogue
    audit (see build_eligibility_sql in app/services/rule_playground.py for the
    exact source table/column and real coverage per field). Filters with no
    real backing data (client-approved-AMC lists, watchlists, compliance flags,
    max drawdown, volatility, downside capture, cap-size exposure, NAV
    coverage, document availability, category/benchmark-change history) are
    intentionally NOT modeled here — the frontend shows them disabled rather
    than this schema accepting params that would silently no-op.
    """

    # ── Core eligibility ───────────────────────────────────────────────────
    bucket_36s: list[str] | None = Field(default=None, description="Multi-select category_taxonomy_current.bucket_36")
    bucket_group: str | None = Field(default=None, description="'ALL Equity' | 'ALL Hybrid' | 'ALL Passive'")
    amc_codes: list[int] | None = Field(default=None, description="Include only these AMCs (amc_mst_new.amc_code)")
    amc_exclude_codes: list[int] | None = Field(default=None, description="Exclude these AMCs")
    status: str = Field(default="Active", description="altstreet_scheme_master.status — 'Active'|'Merged'|'All'")
    plan_type: Literal["direct", "regular"] | None = Field(default=None, description="accord_fintech_scheme_details.plan (5=Direct, 6=Regular — verified clean)")
    option_type: Literal["growth", "idcw"] | None = Field(default=None, description="Best-effort text match on afd.defaultplan — no coded lookup exists")
    min_history_years: float | None = Field(default=None, description="altstreet_scheme_master.launch_date age")
    require_benchmark_mapped: bool = Field(default=False, description="selfmade_scheme_category_benchmark, excludes is_fallback_benchmark")
    data_confidence_min: Literal["High", "Medium", "Low"] | None = Field(
        default=None,
        description="Composite: 40% real-benchmark-mapped + 30% fund age + 30% holdings freshness",
    )

    # ── Performance history ────────────────────────────────────────────────
    min_return_history: Literal["1Y", "3Y", "5Y"] | None = Field(default=None, description="selfmade_scheme_returns non-null check")

    # ── Size / liquidity ───────────────────────────────────────────────────
    aum_min_cr: float | None = None
    aum_max_cr: float | None = None
    expense_ratio_max: float | None = Field(default=None, description="selfmade_expense_ratio (full real coverage — NOT the sparse legacy expenceratio table)")

    # ── Portfolio composition ──────────────────────────────────────────────
    holding_concentration_max: float | None = Field(default=None, description="Max % in top-5 holdings (real accord_fintech_mf_portfolio)")
    top10_concentration_max: float | None = None
    holding_count_min: int | None = None
    holding_count_max: int | None = None
    sector_exposure: dict[str, float] | None = Field(default=None, description="{sector_name: min_pct}, real sect_name column")
    company_include: str | None = Field(default=None, description="Fund must hold a company whose name matches this substring")
    company_exclude: str | None = Field(default=None, description="Fund must NOT hold any company matching this substring")

    # ── Risk ──────────────────────────────────────────────────────────────
    tracking_error_min: float | None = None
    tracking_error_max: float | None = Field(default=None, description="selfmade_scheme_metrics.tracking_error_3yr — full real coverage")
    beta_min: float | None = Field(default=None, description="mf_ratios_defaultbm.beta — PARTIAL, ~17/473 in ranked universe")
    beta_max: float | None = None
    sharpe_min: float | None = Field(default=None, description="selfmade_scheme_metrics.sharpe_ratio_3yr — full real coverage")
    sortino_min: float | None = Field(default=None, description="selfmade_scheme_metrics.sortino_ratio_3yr — PARTIAL, ~18/473 (real, still sparse after the earlier fix)")

    # ── Structural improvement (governed rule-engine metrics) ─────────────
    ir_slope_min: float | None = Field(default=None, description="selfmade_scheme_metrics.ir_slope_6m_proxy — full real coverage")
    outperformance_ratio_min: float | None = Field(default=None, description="Fraction [0,1] of outperformed_1yr/3yr/5yr flags")
    rank_movement_min: int | None = Field(default=None, description="selfmade_ranking_snapshot.rank_delta_6m — now fully populated (was a stub before multiple real recompute runs existed)")

    # ── Lifecycle / regulatory ──────────────────────────────────────────────
    exclude_merged: bool = Field(default=True, description="altstreet_scheme_master.status != 'Merged'")

    # ── Operational / data quality ──────────────────────────────────────────
    holdings_freshness_max_months: int | None = Field(default=None, description="Max age of latest accord_fintech_mf_portfolio.invdate")
    aum_freshness_days: int | None = Field(default=None, description="Max age of latest AUM snapshot")

    # ── Taxonomy ────────────────────────────────────────────────────────────
    exclude_elss: bool = Field(default=False, description="Derived from sm.category text match")
    exclude_thematic: bool = Field(default=False, description="Derived from sm.category text match")


class RuleComponentOut(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    metric_id: str
    metric_name: str
    weight: float
    weight_pct: int
    direction: str
    normalization: str
    window_years: int | None
    display_order: int


class RuleVersionOut(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    version_number: int
    status: str
    components: list[RuleComponentOut]


class SandboxRunRequest(BaseModel):
    """Sandbox filter + metric-weight inputs.

    Field descriptions note which filters are IMPLEMENTED, which are STUB
    (accepted but produce a backend warning), and which are BLOCKED (data gap).
    """

    # ── Metric weights ─────────────────────────────────────────────────────
    components: list[dict] = Field(default_factory=list)

    # ── Eligibility ────────────────────────────────────────────────────────
    category_id: str = Field(
        default="",
        description="Raw altstreet_scheme_master.category. Ignored when bucket_36 or bucket_group is set.",
    )
    # Multi-select bucket_36: preferred when set (overrides category_id)
    bucket_36: str | None = Field(default=None, description="Single 36-bucket filter")
    bucket_36s: list[str] | None = Field(
        default=None,
        description="Multi-select 36-bucket filter; overrides bucket_36 when set",
    )
    categories: list[str] | None = Field(
        default=None,
        description="Multi-select raw altstreet_scheme_master.category values",
    )
    bucket_group: str | None = Field(
        default=None,
        description="Group-level filter: 'ALL Equity' | 'ALL Hybrid' | 'ALL Passive'. "
                    "Overrides category/bucket filters.",
    )
    amc_codes: list[int] | None = Field(default=None, description="Include only these AMCs")
    amc_exclude_codes: list[int] | None = Field(
        default=None,
        description="Exclude these AMCs (NOT IN). Applied after amc_codes include.",
    )
    status: str = Field(default="Active", description="'Active' | 'Merged' | 'Closed' | 'All'")
    aum_min_cr: float | None = Field(default=None)
    aum_max_cr: float | None = Field(default=None)
    aum_freshness_days: int | None = Field(
        default=None,
        description="Maximum age of scheme_aum snapshot in days",
    )
    min_history_years: float | None = Field(default=None)
    expense_ratio_max: float | None = Field(default=None)
    plan_type: Literal["direct", "regular"] | None = Field(default=None)
    option_type: Literal["growth", "idcw"] | None = Field(default=None)

    # Taxonomy toggles (no new DB column needed)
    exclude_elss: bool = Field(
        default=False,
        description="Exclude ELSS funds (tax lock-in). Derived from sm.category.",
    )
    exclude_thematic: bool = Field(
        default=False,
        description="Exclude Thematic Fund and Sector Funds. Derived from sm.category.",
    )

    # ── Data Quality ──────────────────────────────────────────────────────
    exclude_merged: bool = Field(default=True)
    require_benchmark_mapped: bool = Field(default=False)
    holdings_freshness_max_months: int | None = Field(default=None)
    data_confidence_min: Literal["High", "Medium", "Low"] | None = Field(
        default=None,
        description="Composite band: 40% benchmark quality + 30% history + 30% holdings freshness",
    )
    nav_coverage_pct_min: float | None = Field(
        default=None,
        description="[BLOCKED] Skipped until navhist is fully imported and trading_calendar exists",
    )

    # ── Performance History ────────────────────────────────────────────────
    min_return_history: Literal["1Y", "3Y", "5Y"] | None = Field(
        default=None,
        description="Require non-null CAGR return for at least this window",
    )

    # ── Structural Improvement ────────────────────────────────────────────
    ir_percentile_min: float | None = Field(
        default=None,
        description="Minimum IR percentile within category (0–100). Proxy via pct_ir_3yr.",
    )
    outperformance_ratio_min: float | None = Field(
        default=None,
        description="Fraction [0,1] of 1yr/3yr/5yr periods fund must outperform benchmark",
    )
    rank_movement_min: int | None = Field(
        default=None, description="[STUB] rank_delta not yet populated"
    )
    improvement_metric_min: float | None = Field(
        default=None, description="[STUB] IR-trend column not yet computed"
    )

    # ── Risk ──────────────────────────────────────────────────────────────
    tracking_error_min: float | None = Field(
        default=None, description="Minimum 3yr tracking error %"
    )
    tracking_error_max: float | None = Field(
        default=None, description="Maximum 3yr tracking error %"
    )
    beta_min: float | None = Field(default=None)
    beta_max: float | None = Field(default=None)
    sharpe_min: float | None = Field(default=None)
    sortino_min: float | None = Field(default=None)
    volatility_max: float | None = Field(
        default=None,
        description="[STUB] sd_annualised not populated; use tracking_error_max as proxy",
    )
    downside_capture_max: float | None = Field(
        default=None, description="[BLOCKED] Requires full NAV history"
    )

    # ── Portfolio ─────────────────────────────────────────────────────────
    holding_concentration_max: float | None = Field(
        default=None, description="Max % in top-5 holdings"
    )
    top10_concentration_max: float | None = Field(
        default=None, description="Max % in top-10 holdings"
    )
    holding_count_min: int | None = Field(default=None)
    holding_count_max: int | None = Field(default=None)
    sector_exposure: dict[str, float] | None = Field(
        default=None,
        description="Dict of {sector_name: min_pct}. Fund must have ≥ min_pct in each sector.",
    )
    cash_exposure_max: float | None = Field(
        default=None, description="[TIER3] Requires scheme_assetalloc"
    )
    large_cap_exposure_min: float | None = Field(
        default=None, description="[TIER3]"
    )
    mid_cap_exposure_min: float | None = Field(default=None, description="[TIER3]")
    small_cap_exposure_min: float | None = Field(default=None, description="[TIER3]")

    # ── Change-history (Tier 2) ────────────────────────────────────────────
    exclude_category_changed_since_version: int | None = Field(
        default=None, description="[TIER2] Requires versioned taxonomy"
    )
    exclude_benchmark_changed_since_version: int | None = Field(
        default=None, description="[TIER2] Requires versioned benchmark table"
    )


class SandboxRunResult(BaseModel):
    scheme_plan_id: str
    fund_name: str
    default_rank: int
    sandbox_rank: int
    rank_change: int
    default_score: float
    sandbox_score: float
    score_change: float


class SandboxRunResponse(VersionedResponse):
    """Sandbox run output — inherits four VersionedResponse fields (CLAUDE.md rule 2)."""

    results: list[SandboxRunResult]
    promoted_count: int
    dropped_count: int
    warnings: list[str] = Field(
        default_factory=list,
        description="Filters accepted but not applied due to data gaps or stubs",
    )
