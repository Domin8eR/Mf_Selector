"""Rule Playground filter builder.

Assembles the SQL WHERE/JOIN/CTE fragments for sandbox_run based on the
caller's FilterParams.  Pure string/dict construction — no DB I/O — so it
can be unit-tested without a live connection.

CLAUDE.md rule 1: this module never computes metric values; it only adds
filter conditions that reference pre-computed tables (selfmade_scheme_ranking,
selfmade_scheme_metrics, etc.).

Table aliases expected by the calling query in routers/rules.py:
  r   = mf_ratios_defaultbm
  sm  = altstreet_scheme_master
  cr  = mf_cagr_return
  sa  = scheme_aum (latest date subquery — LEFT JOIN, may be NULL)
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FilterParams:
    """All optional sandbox filter inputs.  Every field is Optional / None = disabled."""

    # ── Eligibility ────────────────────────────────────────────────────────
    category: str | None = None
    # Multi-select: bucket_36s wins over category_ids when both are set
    bucket_36: str | None = None          # single-select (kept for backward compat)
    bucket_36s: list[str] | None = None  # multi-select: replaces bucket_36 when set
    categories: list[str] | None = None  # raw altstreet_scheme_master.category multi-select
    bucket_group: str | None = None      # "ALL Equity" / "ALL Hybrid" / "ALL Passive"
    amc_codes: list[int] | None = None
    amc_exclude_codes: list[int] | None = None  # AMCs to exclude (NOT IN)
    status: str = "Active"
    min_history_years: float | None = None
    expense_ratio_max: float | None = None
    aum_min_cr: float | None = None
    aum_max_cr: float | None = None
    aum_freshness_days: int | None = None   # max age of scheme_aum.date in days
    exclude_merged: bool = True
    # Taxonomy toggles (no new column needed — derived from sm.category)
    exclude_elss: bool = False
    exclude_thematic: bool = False

    # ── Data Quality ──────────────────────────────────────────────────────
    require_benchmark_mapped: bool = False
    holdings_freshness_max_months: int | None = None
    data_confidence_min: str | None = None  # "High" | "Medium" | "Low"
    nav_coverage_pct_min: float | None = None  # BLOCKED — trading_calendar missing

    # ── Performance history ────────────────────────────────────────────────
    # "1Y" → requires non-null mf_cagr_return.1yrret
    # "3Y" → requires non-null mf_cagr_return.3yearret
    # "5Y" → requires non-null mf_cagr_return.5yearret
    min_return_history: str | None = None  # "1Y" | "3Y" | "5Y"

    # ── Structural Improvement — backed by selfmade_scheme_ranking ─────────
    ir_percentile_min: float | None = None      # pct_ir_3yr >= x (0–100 scale)
    outperformance_ratio_min: float | None = None  # fraction [0,1]
    rank_movement_min: int | None = None        # rank_delta (stub — all NULL)
    improvement_metric_min: float | None = None  # stub — no pre-computed column

    # ── Risk ──────────────────────────────────────────────────────────────
    tracking_error_min: float | None = None    # selfmade_scheme_metrics.tracking_error_3yr
    tracking_error_max: float | None = None    # same
    volatility_max: float | None = None        # stub — sd_annualised all NULL
    downside_capture_max: float | None = None  # stub — navhist data insufficient
    beta_min: float | None = None              # mf_ratios_defaultbm.beta
    beta_max: float | None = None              # mf_ratios_defaultbm.beta
    sharpe_min: float | None = None            # mf_ratios_defaultbm.sharpe
    sortino_min: float | None = None           # mf_ratios_defaultbm.sortino

    # ── Portfolio ─────────────────────────────────────────────────────────
    holding_concentration_max: float | None = None   # top-5 holdings %
    top10_concentration_max: float | None = None     # top-10 holdings %
    holding_count_min: int | None = None             # number of holdings (min)
    holding_count_max: int | None = None             # number of holdings (max)
    sector_exposure: dict[str, float] | None = None  # {sector: min_pct}
    cash_exposure_max: float | None = None           # Tier 3 — scheme_assetalloc
    large_cap_exposure_min: float | None = None      # Tier 3
    mid_cap_exposure_min: float | None = None        # Tier 3
    small_cap_exposure_min: float | None = None      # Tier 3

    # ── Plan / Option (Tier 3 — inferred mapping) ─────────────────────────
    # NOTE: afd.optiontype codes ('DP','DR','GP','GR'…) are not in a lookup
    # table — inference uses LIKE 'D%' for direct.  Verify against DB before
    # replacing with an authoritative join.
    plan_type: str | None = None    # "direct" | "regular"
    option_type: str | None = None  # "growth" | "idcw"

    # ── Data confidence (Tier 3) ──────────────────────────────────────────
    # Composite: 40% benchmark quality + 30% history + 30% holdings freshness

    # ── Change-history exclusions (Tier 2 — versioned taxonomy required) ──
    exclude_category_changed_since_version: int | None = None
    exclude_benchmark_changed_since_version: int | None = None


@dataclass
class FilterSQL:
    """Output of build_universe_sql — injected into the sandbox run query."""

    ctes: list[str] = field(default_factory=list)
    extra_joins: str = ""
    where_clauses: list[str] = field(default_factory=list)
    params: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def build_universe_sql(filters: FilterParams) -> FilterSQL:  # noqa: C901
    """Build SQL fragments from FilterParams.

    Returns a FilterSQL whose parts are merged into the caller's query like:
        WITH {",".join(ctes)} ...
        FROM ... {extra_joins}
        WHERE {" AND ".join(where_clauses)}
    All filter values are bound via the returned params dict (never interpolated).

    Aliases available in the calling query (routers/rules.py sandbox_run):
        r  = mf_ratios_defaultbm
        sm = altstreet_scheme_master
        cr = mf_cagr_return  (LEFT JOIN, flag='A')
        sa = scheme_aum latest snapshot (LEFT JOIN)
    """
    sql = FilterSQL()

    # ── Track which extra aliases are JOINed to avoid double-joins ────────
    _joined_afd = False    # accord_fintech_scheme_details afd
    _joined_sr  = False    # selfmade_scheme_ranking sr
    _joined_smm = False    # selfmade_scheme_metrics smm
    _joined_ctc = False    # category_taxonomy_current ctc

    def _ensure_afd() -> str:
        nonlocal _joined_afd
        if not _joined_afd:
            sql.extra_joins += (
                " LEFT JOIN accord_fintech_scheme_details afd"
                "  ON afd.schemecode::text = sm.scheme_id"
            )
            _joined_afd = True
        return "afd"

    def _ensure_sr() -> str:
        nonlocal _joined_sr
        if not _joined_sr:
            sql.extra_joins += (
                " LEFT JOIN selfmade_scheme_ranking sr"
                "  ON sr.schemecode::text = sm.scheme_id"
            )
            _joined_sr = True
        return "sr"

    def _ensure_smm() -> str:
        nonlocal _joined_smm
        if not _joined_smm:
            sql.extra_joins += (
                " LEFT JOIN selfmade_scheme_metrics smm"
                "  ON smm.schemecode::text = sm.scheme_id"
            )
            _joined_smm = True
        return "smm"

    def _ensure_ctc(alias: str = "ctc") -> str:
        nonlocal _joined_ctc
        if not _joined_ctc:
            sql.extra_joins += (
                f" LEFT JOIN category_taxonomy_current {alias}"
                f"  ON {alias}.schemecode::text = sm.scheme_id"
            )
            _joined_ctc = True
        return alias

    # ── ELIGIBILITY: category / bucket ────────────────────────────────────

    if filters.bucket_group:
        # Group-level filter (ALL Equity / ALL Hybrid / ALL Passive)
        ctc = _ensure_ctc()
        sql.where_clauses.append(f"{ctc}.bucket_group = :bucket_group")
        sql.params["bucket_group"] = filters.bucket_group

    elif filters.bucket_36s:
        # Multi-select bucket_36
        ctc = _ensure_ctc()
        placeholders = ", ".join(f":b36_{i}" for i in range(len(filters.bucket_36s)))
        sql.where_clauses.append(f"{ctc}.bucket_36 IN ({placeholders})")
        for i, b in enumerate(filters.bucket_36s):
            sql.params[f"b36_{i}"] = b

    elif filters.bucket_36:
        # Single-select bucket_36
        ctc = _ensure_ctc()
        sql.where_clauses.append(f"{ctc}.bucket_36 = :bucket_36")
        sql.params["bucket_36"] = filters.bucket_36

    elif filters.categories:
        # Raw altstreet_scheme_master.category multi-select
        placeholders = ", ".join(f":cat_{i}" for i in range(len(filters.categories)))
        sql.where_clauses.append(f"sm.category IN ({placeholders})")
        for i, c in enumerate(filters.categories):
            sql.params[f"cat_{i}"] = c

    elif filters.category:
        # Single raw category (backward compat)
        sql.where_clauses.append("sm.category = :category")
        sql.params["category"] = filters.category

    # ── ELIGIBILITY: status ───────────────────────────────────────────────
    if filters.status and filters.status.lower() != "all":
        sql.where_clauses.append("sm.status = :status")
        sql.params["status"] = filters.status

    # ── ELIGIBILITY: AMC include ──────────────────────────────────────────
    if filters.amc_codes:
        sql.extra_joins += " JOIN amc_mst_new amn ON amn.amc_code::text = sm.amc"
        placeholders = ", ".join(f":amc_{i}" for i in range(len(filters.amc_codes)))
        sql.where_clauses.append(f"amn.amc_code IN ({placeholders})")
        for i, code in enumerate(filters.amc_codes):
            sql.params[f"amc_{i}"] = code

    # ── ELIGIBILITY: AMC exclude ──────────────────────────────────────────
    if filters.amc_exclude_codes:
        # Uses a subquery to avoid alias conflict with potential include JOIN above
        ex_placeholders = ", ".join(f":amc_ex_{i}" for i in range(len(filters.amc_exclude_codes)))
        sql.where_clauses.append(
            f"sm.amc::integer NOT IN ({ex_placeholders})"
        )
        for i, code in enumerate(filters.amc_exclude_codes):
            sql.params[f"amc_ex_{i}"] = code

    # ── ELIGIBILITY: AUM range ────────────────────────────────────────────
    # sa.total is in lakhs; inputs are crores → ×100
    if filters.aum_min_cr is not None:
        sql.where_clauses.append("(sa.total / 100.0) >= :aum_min")
        sql.params["aum_min"] = float(filters.aum_min_cr)
    if filters.aum_max_cr is not None:
        sql.where_clauses.append("(sa.total / 100.0) <= :aum_max")
        sql.params["aum_max"] = float(filters.aum_max_cr)

    # ── ELIGIBILITY: AUM freshness ────────────────────────────────────────
    # sa already joins latest scheme_aum date in the caller, so if sa.date is
    # old the fund's AUM data is stale.
    if filters.aum_freshness_days is not None:
        sql.where_clauses.append(
            "sa.date IS NOT NULL AND (CURRENT_DATE - sa.date) <= :aum_freshness"
        )
        sql.params["aum_freshness"] = int(filters.aum_freshness_days)

    # ── ELIGIBILITY: minimum history ──────────────────────────────────────
    if filters.min_history_years is not None:
        _ensure_afd()
        sql.where_clauses.append(
            "afd.incept_date IS NOT NULL"
            " AND afd.incept_date <= (NOW() - :hist_interval * INTERVAL '1 year')"
        )
        sql.params["hist_interval"] = float(filters.min_history_years)

    # ── ELIGIBILITY: expense ratio max ────────────────────────────────────
    if filters.expense_ratio_max is not None:
        sql.ctes.append(
            "latest_er AS ("
            "  SELECT DISTINCT ON (schemecode) schemecode, expratio"
            "  FROM expenceratio"
            "  WHERE expratio IS NOT NULL"
            "  ORDER BY schemecode, date DESC"
            ")"
        )
        sql.extra_joins += " LEFT JOIN latest_er ler ON ler.schemecode::text = sm.scheme_id"
        sql.where_clauses.append("(ler.expratio IS NULL OR ler.expratio <= :er_max)")
        sql.params["er_max"] = float(filters.expense_ratio_max)

    # ── ELIGIBILITY: exclude merged ───────────────────────────────────────
    if filters.exclude_merged:
        _ensure_afd()
        sql.where_clauses.append("(afd.status IS NULL OR afd.status != 'Merged')")

    # ── TAXONOMY TOGGLES ──────────────────────────────────────────────────
    if filters.exclude_elss:
        sql.where_clauses.append("sm.category != 'Equity Linked Savings Scheme'")

    if filters.exclude_thematic:
        sql.where_clauses.append(
            "sm.category NOT IN ('Thematic Fund', 'Sector Funds')"
        )

    # ── DATA QUALITY: benchmark mapped ─────────────────────────────────
    if filters.require_benchmark_mapped:
        sql.where_clauses.append(
            "EXISTS ("
            "  SELECT 1 FROM selfmade_scheme_category_benchmark scb"
            "  WHERE scb.schemecode::text = sm.scheme_id"
            "    AND NOT scb.is_fallback_benchmark"
            ")"
        )

    # ── DATA QUALITY: holdings freshness ─────────────────────────────────
    if filters.holdings_freshness_max_months is not None:
        sql.ctes.append(
            "holdings_freshness AS ("
            "  SELECT schemecode,"
            "    EXTRACT(MONTH FROM AGE(CURRENT_DATE, MAX(invdate)))::int AS freshness_months"
            "  FROM accord_fintech_mf_portfolio"
            "  GROUP BY schemecode"
            ")"
        )
        sql.extra_joins += " LEFT JOIN holdings_freshness hf ON hf.schemecode::text = sm.scheme_id"
        sql.where_clauses.append(
            "(hf.freshness_months IS NULL OR hf.freshness_months <= :hf_max)"
        )
        sql.params["hf_max"] = int(filters.holdings_freshness_max_months)

    # ── DATA QUALITY: data confidence ─────────────────────────────────────
    if filters.data_confidence_min is not None:
        band_threshold = {"High": 70.0, "Medium": 40.0, "Low": 0.0}
        min_score = band_threshold.get(filters.data_confidence_min, 0.0)
        _ensure_afd()
        _ensure_smm()
        sql.ctes.append(
            "dc_freshness AS ("
            "  SELECT schemecode,"
            "    GREATEST(0, 1.0 - "
            "      EXTRACT(MONTH FROM AGE(CURRENT_DATE, MAX(invdate))) / 24.0"
            "    ) AS freshness_score"
            "  FROM accord_fintech_mf_portfolio GROUP BY schemecode"
            ")"
        )
        sql.extra_joins += " LEFT JOIN dc_freshness dcf ON dcf.schemecode::text = sm.scheme_id"
        sql.where_clauses.append(
            "("
            "  40.0 * (CASE WHEN smm.is_fallback_benchmark THEN 0.0 ELSE 1.0 END)"
            "  + 30.0 * LEAST(1.0, EXTRACT(YEAR FROM AGE(NOW(), afd.incept_date)) / 10.0)"
            "  + 30.0 * COALESCE(dcf.freshness_score, 0.0)"
            ") >= :dc_min"
        )
        sql.params["dc_min"] = min_score

    # ── PERFORMANCE HISTORY: minimum return data availability ─────────────
    if filters.min_return_history:
        col_map = {
            "1Y": 'cr."1yrret"',
            "3Y": 'cr."3yearret"',
            "5Y": 'cr."5yearret"',
        }
        col = col_map.get(filters.min_return_history.upper())
        if col:
            sql.where_clauses.append(f"{col} IS NOT NULL")
        else:
            sql.warnings.append(
                f"min_return_history value '{filters.min_return_history}' unrecognised; use 1Y, 3Y, or 5Y"
            )

    # ── NAV COVERAGE (stub) ───────────────────────────────────────────────
    if filters.nav_coverage_pct_min is not None:
        sql.warnings.append(
            "nav_coverage filter skipped — trading_calendar table does not exist"
            " and navhist only has 9 days of data; import full NAV history first"
        )

    # ── STRUCTURAL IMPROVEMENT: IR percentile ─────────────────────────────
    if filters.ir_percentile_min is not None:
        _ensure_sr()
        sql.where_clauses.append("sr.pct_ir_3yr >= :ir_pct_min")
        sql.params["ir_pct_min"] = float(filters.ir_percentile_min)

    # ── STRUCTURAL IMPROVEMENT: outperformance ratio ──────────────────────
    if filters.outperformance_ratio_min is not None:
        _ensure_smm()
        ratio = float(filters.outperformance_ratio_min)
        if ratio <= 0.34:
            sql.where_clauses.append(
                "(smm.outperformed_1yr OR smm.outperformed_3yr OR smm.outperformed_5yr)"
            )
        elif ratio <= 0.67:
            sql.where_clauses.append(
                "(CASE WHEN smm.outperformed_1yr THEN 1 ELSE 0 END"
                " + CASE WHEN smm.outperformed_3yr THEN 1 ELSE 0 END"
                " + CASE WHEN smm.outperformed_5yr THEN 1 ELSE 0 END) >= 2"
            )
        else:
            sql.where_clauses.append(
                "smm.outperformed_1yr AND smm.outperformed_3yr AND smm.outperformed_5yr"
            )

    # ── STRUCTURAL IMPROVEMENT: rank movement (stub) ──────────────────────
    if filters.rank_movement_min is not None:
        sql.warnings.append(
            "rank_movement filter skipped — selfmade_scheme_ranking.rank_delta"
            " is not yet populated (only one ranking run exists)"
        )

    # ── STRUCTURAL IMPROVEMENT: improvement metric (stub) ─────────────────
    if filters.improvement_metric_min is not None:
        sql.warnings.append(
            "improvement_metric filter skipped — requires a pre-computed"
            " IR-trend column; add a Celery job to populate it first"
        )

    # ── RISK: tracking error (min + max) ──────────────────────────────────
    if filters.tracking_error_min is not None or filters.tracking_error_max is not None:
        _ensure_smm()
        if filters.tracking_error_min is not None:
            sql.where_clauses.append(
                "(smm.tracking_error_3yr IS NOT NULL AND smm.tracking_error_3yr >= :te_min)"
            )
            sql.params["te_min"] = float(filters.tracking_error_min)
        if filters.tracking_error_max is not None:
            sql.where_clauses.append(
                "(smm.tracking_error_3yr IS NULL OR smm.tracking_error_3yr <= :te_max)"
            )
            sql.params["te_max"] = float(filters.tracking_error_max)

    # ── RISK: beta range ──────────────────────────────────────────────────
    # r (mf_ratios_defaultbm) is already joined by the calling query
    if filters.beta_min is not None:
        sql.where_clauses.append("r.beta IS NOT NULL AND r.beta >= :beta_min")
        sql.params["beta_min"] = float(filters.beta_min)
    if filters.beta_max is not None:
        sql.where_clauses.append("(r.beta IS NULL OR r.beta <= :beta_max)")
        sql.params["beta_max"] = float(filters.beta_max)

    # ── RISK: Sharpe min ──────────────────────────────────────────────────
    if filters.sharpe_min is not None:
        sql.where_clauses.append("r.sharpe IS NOT NULL AND r.sharpe >= :sharpe_min")
        sql.params["sharpe_min"] = float(filters.sharpe_min)

    # ── RISK: Sortino min ─────────────────────────────────────────────────
    if filters.sortino_min is not None:
        sql.where_clauses.append("r.sortino IS NOT NULL AND r.sortino >= :sortino_min")
        sql.params["sortino_min"] = float(filters.sortino_min)

    # ── RISK: volatility (stub) ───────────────────────────────────────────
    if filters.volatility_max is not None:
        sql.warnings.append(
            "volatility filter skipped — mf_ratios_defaultbm.sd_annualised"
            " has no populated rows; use tracking_error_max as a risk proxy for now"
        )

    # ── RISK: downside capture (stub) ─────────────────────────────────────
    if filters.downside_capture_max is not None:
        sql.warnings.append(
            "downside_capture filter skipped — requires daily price series"
            " vs benchmark; navhist currently only has 9 days of data"
        )

    # ── PORTFOLIO: top-5 holding concentration ───────────────────────────
    if filters.holding_concentration_max is not None:
        sql.ctes.append(
            "top5_conc AS ("
            "  SELECT p.schemecode, SUM(p.holdpercentage) AS top5_pct"
            "  FROM ("
            "    SELECT schemecode, holdpercentage,"
            "      ROW_NUMBER() OVER (PARTITION BY schemecode ORDER BY holdpercentage DESC NULLS LAST) rn"
            "    FROM accord_fintech_mf_portfolio afp"
            "    WHERE afp.invdate = ("
            "      SELECT MAX(invdate) FROM accord_fintech_mf_portfolio"
            "      WHERE schemecode = afp.schemecode"
            "    )"
            "  ) p WHERE p.rn <= 5"
            "  GROUP BY p.schemecode"
            ")"
        )
        sql.extra_joins += " LEFT JOIN top5_conc tc ON tc.schemecode::text = sm.scheme_id"
        sql.where_clauses.append("(tc.top5_pct IS NULL OR tc.top5_pct <= :conc_max)")
        sql.params["conc_max"] = float(filters.holding_concentration_max)

    # ── PORTFOLIO: top-10 holding concentration ───────────────────────────
    if filters.top10_concentration_max is not None:
        sql.ctes.append(
            "top10_conc AS ("
            "  SELECT p.schemecode, SUM(p.holdpercentage) AS top10_pct"
            "  FROM ("
            "    SELECT schemecode, holdpercentage,"
            "      ROW_NUMBER() OVER (PARTITION BY schemecode ORDER BY holdpercentage DESC NULLS LAST) rn"
            "    FROM accord_fintech_mf_portfolio afp10"
            "    WHERE afp10.invdate = ("
            "      SELECT MAX(invdate) FROM accord_fintech_mf_portfolio"
            "      WHERE schemecode = afp10.schemecode"
            "    )"
            "  ) p WHERE p.rn <= 10"
            "  GROUP BY p.schemecode"
            ")"
        )
        sql.extra_joins += " LEFT JOIN top10_conc tc10 ON tc10.schemecode::text = sm.scheme_id"
        sql.where_clauses.append("(tc10.top10_pct IS NULL OR tc10.top10_pct <= :conc10_max)")
        sql.params["conc10_max"] = float(filters.top10_concentration_max)

    # ── PORTFOLIO: number of holdings ─────────────────────────────────────
    if filters.holding_count_min is not None or filters.holding_count_max is not None:
        sql.ctes.append(
            "holding_count AS ("
            "  SELECT schemecode, COUNT(*) AS cnt"
            "  FROM accord_fintech_mf_portfolio afp_hc"
            "  WHERE afp_hc.invdate = ("
            "    SELECT MAX(invdate) FROM accord_fintech_mf_portfolio"
            "    WHERE schemecode = afp_hc.schemecode"
            "  )"
            "  GROUP BY schemecode"
            ")"
        )
        sql.extra_joins += " LEFT JOIN holding_count hc ON hc.schemecode::text = sm.scheme_id"
        if filters.holding_count_min is not None:
            sql.where_clauses.append("(hc.cnt IS NOT NULL AND hc.cnt >= :hc_min)")
            sql.params["hc_min"] = int(filters.holding_count_min)
        if filters.holding_count_max is not None:
            sql.where_clauses.append("(hc.cnt IS NULL OR hc.cnt <= :hc_max)")
            sql.params["hc_max"] = int(filters.holding_count_max)

    # ── PORTFOLIO: sector exposure ────────────────────────────────────────
    if filters.sector_exposure:
        for i, (sector, min_pct) in enumerate(filters.sector_exposure.items()):
            cte_name = f"sector_exp_{i}"
            param_s  = f"sector_{i}"
            param_p  = f"sector_pct_{i}"
            sql.ctes.append(
                f"{cte_name} AS ("
                f"  SELECT schemecode, SUM(holdpercentage) AS sector_pct"
                f"  FROM accord_fintech_mf_portfolio afps"
                f"  WHERE afps.invdate = ("
                f"    SELECT MAX(invdate) FROM accord_fintech_mf_portfolio"
                f"    WHERE schemecode = afps.schemecode"
                f"  ) AND sect_name = :{param_s}"
                f"  GROUP BY schemecode"
                f")"
            )
            sql.extra_joins += (
                f" LEFT JOIN {cte_name} se{i} ON se{i}.schemecode::text = sm.scheme_id"
            )
            sql.where_clauses.append(
                f"(se{i}.sector_pct IS NOT NULL AND se{i}.sector_pct >= :{param_p})"
            )
            sql.params[param_s] = sector
            sql.params[param_p] = float(min_pct)

    # ── PLAN / OPTION TYPE ────────────────────────────────────────────────
    if filters.plan_type or filters.option_type:
        _ensure_afd()
        if filters.plan_type:
            # afd.optiontype codes are not in a lookup table; 'D%' = Direct is
            # a best-effort inference.  Verify by querying DISTINCT optiontype
            # from accord_fintech_scheme_details before replacing.
            if filters.plan_type.lower() == "direct":
                sql.where_clauses.append("afd.optiontype LIKE 'D%'")
            else:
                sql.where_clauses.append("(afd.optiontype IS NULL OR afd.optiontype NOT LIKE 'D%')")
        if filters.option_type:
            if filters.option_type.lower() == "growth":
                sql.where_clauses.append("LOWER(afd.defaultplan) LIKE '%growth%'")
            else:
                sql.where_clauses.append(
                    "(LOWER(afd.defaultplan) LIKE '%dividend%'"
                    " OR LOWER(afd.defaultplan) LIKE '%idcw%')"
                )

    # ── PORTFOLIO: cap-size / cash (Tier 3) ───────────────────────────────
    asset_alloc_stubs = [
        (filters.cash_exposure_max,      "cash_exposure_max"),
        (filters.large_cap_exposure_min, "large_cap_exposure_min"),
        (filters.mid_cap_exposure_min,   "mid_cap_exposure_min"),
        (filters.small_cap_exposure_min, "small_cap_exposure_min"),
    ]
    for val, name in asset_alloc_stubs:
        if val is not None:
            sql.warnings.append(
                f"{name} filter deferred to Tier 3 — requires asset_allocation"
                " service (scheme_assetalloc midpoint bucketing)"
            )

    # ── CHANGE-HISTORY EXCLUSIONS (Tier 2) ────────────────────────────────
    if filters.exclude_category_changed_since_version is not None:
        sql.warnings.append(
            "exclude_category_changed_since_version skipped — requires"
            " category_taxonomy_mapping versioned table (Tier 2)"
        )
    if filters.exclude_benchmark_changed_since_version is not None:
        sql.warnings.append(
            "exclude_benchmark_changed_since_version skipped — requires"
            " versioned selfmade_scheme_category_benchmark (Tier 2)"
        )

    return sql
