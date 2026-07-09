"""Rule set endpoints.

The Altstreet_AI database does not yet contain the governance tables defined
in app/models/rules.py (rule_set, rule_version, rule_component, etc.).
We return a deterministic default rule set based on metrics in mf_ratios_defaultbm
and mf_cagr_return; replace the hardcoded defaults with DB reads once the
governance schema is migrated.

/sandbox/run now accepts the full filter surface defined in SandboxRunRequest
and uses build_universe_sql() from app/services/rule_playground.py to assemble
the WHERE/JOIN/CTE clauses.  Every response inherits VersionedResponse (rule 2).
"""

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.schemas.rules import (
    RuleComponentOut,
    RuleVersionOut,
    SandboxRunRequest,
    SandboxRunResponse,
    SandboxRunResult,
)
from app.services.rule_playground import FilterParams, build_universe_sql

router = APIRouter(prefix="/rules", tags=["rules"])

# Default rules based on metrics actually present in Altstreet_AI
_DEFAULT_COMPONENTS = [
    {
        "id": "RC-SHARPE",
        "metric_id": "SHARPE",
        "metric_name": "Sharpe Ratio",
        "weight": 0.35,
        "weight_pct": 35,
        "direction": "higher_better",
        "normalization": "percentile_rank",
        "window_years": 1,
        "display_order": 1,
    },
    {
        "id": "RC-ALPHA",
        "metric_id": "ALPHA",
        "metric_name": "Alpha (vs Benchmark)",
        "weight": 0.25,
        "weight_pct": 25,
        "direction": "higher_better",
        "normalization": "percentile_rank",
        "window_years": 1,
        "display_order": 2,
    },
    {
        "id": "RC-RET3Y",
        "metric_id": "RET_3Y",
        "metric_name": "3Y CAGR Return",
        "weight": 0.25,
        "weight_pct": 25,
        "direction": "higher_better",
        "normalization": "percentile_rank",
        "window_years": 3,
        "display_order": 3,
    },
    {
        "id": "RC-SORTINO",
        "metric_id": "SORTINO",
        "metric_name": "Sortino Ratio",
        "weight": 0.15,
        "weight_pct": 15,
        "direction": "higher_better",
        "normalization": "percentile_rank",
        "window_years": 1,
        "display_order": 4,
    },
]

_DEFAULT_VERSION = {
    "id": "CLIENT-DEFAULT-v1",
    "version_number": 1,
    "status": "active",
    "components": _DEFAULT_COMPONENTS,
}

# Map metric IDs to actual DB columns in mf_ratios_defaultbm / mf_cagr_return
_METRIC_COL_MAP = {
    "SHARPE":  "r.sharpe",
    "ALPHA":   "r.alpha",
    "BETA":    "r.beta",
    "SORTINO": "r.sortino",
    "RET_1Y":  'cr."1yrret"',
    "RET_3Y":  'cr."3yearret"',
    "RET_5Y":  'cr."5yearret"',
}


@router.get("/current")
def get_current_rules(
    rule_set_id: str = "CLIENT-DEFAULT",
    db: Session = Depends(get_db),
) -> dict:
    return _DEFAULT_VERSION


@router.get("/versions")
def list_versions(rule_set_id: str = "CLIENT-DEFAULT", db: Session = Depends(get_db)) -> list:
    # Return stub for legacy v1 endpoint; real v2 list is GET /rules/all-versions
    return [_DEFAULT_VERSION]


@router.get("/pending-approvals")
def pending_approvals(db: Session = Depends(get_db)) -> list:
    return []


@router.get("/amcs")
def list_amcs(db: Session = Depends(get_db)) -> list[dict]:
    """All AMCs available for the category/AMC eligibility filter."""
    rows = db.execute(text(
        "SELECT amc_code, s_name FROM amc_mst_new ORDER BY s_name"
    )).fetchall()
    return [{"amc_code": r[0], "name": r[1]} for r in rows]


@router.get("/sectors")
def list_sectors(db: Session = Depends(get_db)) -> list[dict]:
    """Distinct sector names from the latest portfolio disclosure.

    Used to populate the sector multi-select in the Rule Playground filter panel.
    Returns sectors that appear in at least 5 schemes to filter out data-quality noise.
    """
    try:
        rows = db.execute(text("""
            SELECT sect_name, COUNT(DISTINCT schemecode) AS scheme_count
            FROM accord_fintech_mf_portfolio
            WHERE sect_name IS NOT NULL AND sect_name != ''
            GROUP BY sect_name
            HAVING COUNT(DISTINCT schemecode) >= 5
            ORDER BY scheme_count DESC, sect_name
            LIMIT 60
        """)).fetchall()
        return [{"name": r[0], "scheme_count": int(r[1])} for r in rows]
    except Exception:
        return []


@router.post("/sandbox/run", response_model=SandboxRunResponse)
def sandbox_run(body: SandboxRunRequest, db: Session = Depends(get_db)) -> SandboxRunResponse:
    """
    Re-rank funds using the submitted metric weights, filtered by the full
    filter surface in SandboxRunRequest.

    Metric ranking uses mf_ratios_defaultbm and mf_cagr_return (percentile-rank
    per metric, then weighted sum).  Filters are assembled by build_universe_sql()
    and applied as WHERE/JOIN/CTE clauses — no metric computation at request time
    (CLAUDE.md rule 1).
    """
    components = body.components
    available = {c["metric_id"] for c in components if c["metric_id"] in _METRIC_COL_MAP}

    if not components or not available:
        return SandboxRunResponse(
            data_version=settings.data_version,
            rule_version=settings.rule_version,
            calculation_version=settings.calculation_version,
            as_of_date=date.today(),
            results=[],
            promoted_count=0,
            dropped_count=0,
            warnings=["No valid metric components provided"],
        )

    # Build filter fragments — map every SandboxRunRequest field to FilterParams
    fp = FilterParams(
        category=body.category_id or None,
        bucket_36=body.bucket_36,
        bucket_36s=body.bucket_36s,
        categories=body.categories,
        bucket_group=body.bucket_group,
        amc_codes=body.amc_codes,
        amc_exclude_codes=body.amc_exclude_codes,
        status=body.status,
        min_history_years=body.min_history_years,
        expense_ratio_max=body.expense_ratio_max,
        aum_min_cr=body.aum_min_cr,
        aum_max_cr=body.aum_max_cr,
        aum_freshness_days=body.aum_freshness_days,
        exclude_merged=body.exclude_merged,
        exclude_elss=body.exclude_elss,
        exclude_thematic=body.exclude_thematic,
        require_benchmark_mapped=body.require_benchmark_mapped,
        holdings_freshness_max_months=body.holdings_freshness_max_months,
        data_confidence_min=body.data_confidence_min,
        nav_coverage_pct_min=body.nav_coverage_pct_min,
        min_return_history=body.min_return_history,
        ir_percentile_min=body.ir_percentile_min,
        outperformance_ratio_min=body.outperformance_ratio_min,
        rank_movement_min=body.rank_movement_min,
        improvement_metric_min=body.improvement_metric_min,
        tracking_error_min=body.tracking_error_min,
        tracking_error_max=body.tracking_error_max,
        beta_min=body.beta_min,
        beta_max=body.beta_max,
        sharpe_min=body.sharpe_min,
        sortino_min=body.sortino_min,
        volatility_max=body.volatility_max,
        downside_capture_max=body.downside_capture_max,
        holding_concentration_max=body.holding_concentration_max,
        top10_concentration_max=body.top10_concentration_max,
        holding_count_min=body.holding_count_min,
        holding_count_max=body.holding_count_max,
        sector_exposure=body.sector_exposure,
        cash_exposure_max=body.cash_exposure_max,
        large_cap_exposure_min=body.large_cap_exposure_min,
        mid_cap_exposure_min=body.mid_cap_exposure_min,
        small_cap_exposure_min=body.small_cap_exposure_min,
        plan_type=body.plan_type,
        option_type=body.option_type,
        exclude_category_changed_since_version=body.exclude_category_changed_since_version,
        exclude_benchmark_changed_since_version=body.exclude_benchmark_changed_since_version,
    )
    filter_sql = build_universe_sql(fp)

    # Metric SELECT columns
    metric_cols = ", ".join(
        f"{_METRIC_COL_MAP[m]} AS {m.lower()}" for m in available
    )

    # CTE prefix
    cte_prefix = ""
    if filter_sql.ctes:
        cte_prefix = "WITH " + ", ".join(filter_sql.ctes) + " "

    # WHERE clauses (filter_sql.where_clauses are already included via build_universe_sql;
    # baseline conditions handled by filter_sql for status and category)
    and_where = (" AND " + " AND ".join(filter_sql.where_clauses)) if filter_sql.where_clauses else ""

    sql_str = (
        f"{cte_prefix}"
        f"SELECT sm.scheme_id, sm.scheme_name, {metric_cols} "
        "FROM mf_ratios_defaultbm r "
        "JOIN altstreet_scheme_master sm ON sm.scheme_id::integer = r.schemecode "
        "LEFT JOIN mf_cagr_return cr ON cr.schemecode::integer = sm.scheme_id::integer AND cr.flag='A' "
        "LEFT JOIN scheme_aum sa ON sa.schemecode::integer = sm.scheme_id::integer "
        f"{filter_sql.extra_joins} "
        f"WHERE r.flag='A'{and_where} "
        "ORDER BY sm.scheme_id"
    )

    params = dict(filter_sql.params)
    rows = db.execute(text(sql_str), params).fetchall()

    cols = ["scheme_id", "fund_name"] + [m.lower() for m in available]
    fund_data = [dict(zip(cols, r)) for r in rows]

    # Percentile-rank each metric within the result set
    weights = {c["metric_id"]: float(c["weight"]) / 100 for c in components}
    for mid in available:
        col = mid.lower()
        vals = sorted(
            [(i, float(f[col])) for i, f in enumerate(fund_data) if f.get(col) is not None],
            key=lambda x: x[1],
        )
        n = len(vals)
        for rank, (i, _) in enumerate(vals):
            fund_data[i][f"norm_{col}"] = (rank + 1) / n if n > 0 else 0.0

    for f in fund_data:
        f["sandbox_score"] = sum(
            f.get(f"norm_{mid.lower()}", 0.0) * weights.get(mid, 0.0)
            for mid in available
        )

    default_ranked = sorted(fund_data, key=lambda x: x.get("norm_sharpe", 0.0), reverse=True)
    default_rank_map = {f["scheme_id"]: i + 1 for i, f in enumerate(default_ranked)}

    sandbox_ranked = sorted(fund_data, key=lambda x: x["sandbox_score"], reverse=True)

    results: list[SandboxRunResult] = []
    promoted = dropped = 0
    for sb_rank, f in enumerate(sandbox_ranked, 1):
        def_rank = default_rank_map.get(f["scheme_id"], sb_rank)
        change = def_rank - sb_rank
        if change > 0:
            promoted += 1
        elif change < 0:
            dropped += 1
        def_score = round(def_rank / max(len(fund_data), 1) * 100, 1)
        sb_score = round(f["sandbox_score"] * 100, 1)
        results.append(SandboxRunResult(
            scheme_plan_id=f["scheme_id"],
            fund_name=f["fund_name"],
            default_rank=def_rank,
            sandbox_rank=sb_rank,
            rank_change=change,
            default_score=def_score,
            sandbox_score=sb_score,
            score_change=round(sb_score - def_score, 1),
        ))

    # as_of_date: prefer selfmade_scheme_ranking (more recent), fall back to ratios
    row = db.execute(text(
        "SELECT MAX(as_of_date) FROM selfmade_scheme_ranking"
    )).scalar()
    as_of = row if row else date.today()

    return SandboxRunResponse(
        data_version=settings.data_version,
        rule_version=settings.rule_version,
        calculation_version=settings.calculation_version,
        as_of_date=as_of,
        results=results,
        promoted_count=promoted,
        dropped_count=dropped,
        warnings=filter_sql.warnings,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# V2 endpoints — read from selfmade_ tables, real composite_score_v2 engine
# ═══════════════════════════════════════════════════════════════════════════════

import json
from datetime import datetime

from pydantic import BaseModel

from app.quant.metrics import percentile_rank
from app.quant.formula_parser import validate_formula

# ── Metric vocabulary for rule components ─────────────────────────────────────

METRIC_VOCAB: dict[str, dict] = {
    "information_ratio_3yr": {
        "label": "IR₃ (3Y Information Ratio)",
        "source": "selfmade_scheme_metrics",
        "direction": "higher_better",
        "window_months": 36,
        "short_window": False,
    },
    "sharpe_ratio_3yr": {
        "label": "Sharpe₃ (3Y Sharpe Ratio)",
        "source": "selfmade_scheme_metrics",
        "direction": "higher_better",
        "window_months": 36,
        "short_window": False,
    },
    "tracking_error_3yr": {
        "label": "TE₃ (3Y Tracking Error)",
        "source": "selfmade_scheme_metrics",
        "direction": "lower_better",
        "window_months": 36,
        "short_window": False,
    },
    "ir_slope_6m_proxy": {
        "label": "IR Slope (6m proxy)",
        "source": "selfmade_scheme_metrics",
        "direction": "higher_better",
        "window_months": 6,
        "short_window": True,
    },
    "jensens_alpha_3yr": {
        "label": "Alpha₃ (3Y Jensen's Alpha)",
        "source": "selfmade_scheme_metrics",
        "direction": "higher_better",
        "window_months": 36,
        "short_window": False,
    },
    "fund_1yr_ret": {
        "label": "1Y Fund Return",
        "source": "selfmade_scheme_returns",
        "direction": "higher_better",
        "window_months": 12,
        "short_window": True,
    },
    "fund_3yr_ret": {
        "label": "3Y Fund Return (CAGR)",
        "source": "selfmade_scheme_returns",
        "direction": "higher_better",
        "window_months": 36,
        "short_window": False,
    },
    "fund_5yr_ret": {
        "label": "5Y Fund Return (CAGR)",
        "source": "selfmade_scheme_returns",
        "direction": "higher_better",
        "window_months": 60,
        "short_window": False,
    },
    "active_1yr_ret": {
        "label": "1Y Active Return",
        "source": "selfmade_scheme_returns",
        "direction": "higher_better",
        "window_months": 12,
        "short_window": True,
    },
    "active_3yr_ret": {
        "label": "3Y Active Return (CAGR)",
        "source": "selfmade_scheme_returns",
        "direction": "higher_better",
        "window_months": 36,
        "short_window": False,
    },
    "active_5yr_ret": {
        "label": "5Y Active Return (CAGR)",
        "source": "selfmade_scheme_returns",
        "direction": "higher_better",
        "window_months": 60,
        "short_window": False,
    },
    "expense_ratio_pct": {
        "label": "Expense Ratio %",
        "source": "selfmade_expense_ratio",
        "direction": "lower_better",
        "window_months": None,
        "short_window": False,
    },
    "rank_delta_6m": {
        "label": "Rank Change (6m)",
        "source": "selfmade_ranking_snapshot",
        "direction": "lower_better",
        "window_months": 6,
        "short_window": True,
    },
}

_ALL_METRIC_COLS = list(METRIC_VOCAB.keys())


def _load_universe(category: str, db: "Session") -> list[dict]:
    """
    Load all ranked funds for a category from the latest snapshot,
    joining all selfmade_ metric tables in one query.
    Returns a list of dicts with schemecode, fund_name, default_rank, and all metric cols.
    """
    rows = db.execute(text("""
        SELECT
            s.schemecode,
            s.fund_name,
            s.rank_in_category         AS default_rank,
            s.composite_score_v2       AS default_score,
            s.rank_delta_6m,
            -- selfmade_scheme_metrics
            sm.information_ratio_3yr,
            sm.sharpe_ratio_3yr,
            sm.tracking_error_3yr,
            sm.ir_slope_6m_proxy,
            sm.jensens_alpha_3yr,
            -- selfmade_scheme_returns
            sr.fund_1yr_ret,
            sr.fund_3yr_ret,
            sr.fund_5yr_ret,
            sr.active_1yr_ret,
            sr.active_3yr_ret,
            sr.active_5yr_ret,
            -- selfmade_expense_ratio
            er.expense_ratio_pct
        FROM selfmade_ranking_snapshot s
        LEFT JOIN selfmade_scheme_metrics sm ON sm.schemecode = s.schemecode
        LEFT JOIN selfmade_scheme_returns  sr ON sr.schemecode = s.schemecode
        LEFT JOIN selfmade_expense_ratio   er ON er.schemecode = s.schemecode
        WHERE s.category = :cat
          AND s.snapshot_date = (
              SELECT MAX(snapshot_date) FROM selfmade_ranking_snapshot WHERE category = :cat
          )
        ORDER BY s.rank_in_category
    """), {"cat": category}).fetchall()

    _COLS = [
        "schemecode", "fund_name", "default_rank", "default_score", "rank_delta_6m",
        "information_ratio_3yr", "sharpe_ratio_3yr", "tracking_error_3yr",
        "ir_slope_6m_proxy", "jensens_alpha_3yr",
        "fund_1yr_ret", "fund_3yr_ret", "fund_5yr_ret",
        "active_1yr_ret", "active_3yr_ret", "active_5yr_ret",
        "expense_ratio_pct",
    ]
    return [dict(zip(_COLS, r)) for r in rows]


# ── Pydantic schemas (v2 endpoints) ──────────────────────────────────────────

class RuleComponentV2(BaseModel):
    metric_column: str
    direction: str = "higher_better"
    weight: float          # 0.0–1.0 (not percent)
    formula_text: str | None = None


class SandboxRunV2Request(BaseModel):
    category: str = "Equity — Large Cap"
    rule_components: list[RuleComponentV2]
    evaluation_date: str | None = None


class SandboxFundResult(BaseModel):
    schemecode: int
    fund_name: str
    default_rank: int
    sandbox_rank: int
    rank_change: int
    default_score: float
    sandbox_score: float


class SandboxRunV2Response(BaseModel):
    data_version: str
    rule_version: str
    calculation_version: str
    as_of_date: str
    category: str
    fund_count: int
    promoted_count: int
    dropped_count: int
    no_change_count: int
    top10_turnover_pct: float
    entering_top10: list[str]
    leaving_top10: list[str]
    results: list[SandboxFundResult]
    warnings: list[str]


class FormulaValidateRequest(BaseModel):
    formula_text: str
    available_variables: list[str] | None = None


class SubmitForApprovalRequest(BaseModel):
    rule_components: list[RuleComponentV2]
    rationale: str
    sandbox_run_summary: dict | None = None
    category: str = "Equity — Large Cap"
    submitted_by: str = "Unknown"


# ── GET /rules/default ────────────────────────────────────────────────────────

@router.get("/default")
def get_default_rule(db: Session = Depends(get_db)) -> dict:
    """
    Return the real current active rule version and its components from selfmade_rule_component.
    Read-only; the Rule Playground uses this to pre-populate the editor and as the
    reference baseline for diff calculations.
    """
    rv = db.execute(text("""
        SELECT rv.id, rv.version_label, rv.is_active, rv.status, rv.change_note, rv.created_at
        FROM selfmade_rule_version rv
        JOIN selfmade_rule_set rs ON rs.id = rv.rule_set_id
        WHERE rv.is_active = true
        ORDER BY rv.id DESC
        LIMIT 1
    """)).fetchone()

    if not rv:
        return {
            "data_version": settings.data_version,
            "rule_version": "v1.0",
            "calculation_version": "2.0",
            "as_of_date": str(date.today()),
            "version_label": "v1.0",
            "status": "active",
            "components": [],
        }

    components = db.execute(text("""
        SELECT id, component_name, metric_column, metric_source, direction, weight, label_display, sort_order
        FROM selfmade_rule_component
        WHERE rule_version_id = :rv_id
        ORDER BY sort_order, id
    """), {"rv_id": rv[0]}).fetchall()

    return {
        "data_version": settings.data_version,
        "rule_version": rv[1],
        "calculation_version": "2.0",
        "as_of_date": str(date.today()),
        "version_label": rv[1],
        "status": rv[3] if rv[3] else "active",
        "change_note": rv[4],
        "components": [
            {
                "id": c[0],
                "component_name": c[1],
                "metric_column":  c[2],
                "metric_source":  c[3],
                "direction":      c[4],
                "weight":         float(c[5]),
                "weight_pct":     round(float(c[5]) * 100, 1),
                "label_display":  c[6],
                "sort_order":     c[7],
            }
            for c in components
        ],
        "metric_vocab": {
            k: {
                "label":          v["label"],
                "direction":      v["direction"],
                "window_months":  v["window_months"],
                "short_window":   v["short_window"],
            }
            for k, v in METRIC_VOCAB.items()
        },
    }


# ── POST /rules/formula/validate ─────────────────────────────────────────────

@router.post("/formula/validate")
def formula_validate(
    body: FormulaValidateRequest,
    db: Session = Depends(get_db),
) -> dict:
    """
    Validate a formula expression using the safe AST parser (no eval).
    Returns valid, parsed_variables, error_message, error_type, sample_preview.
    The sample_preview evaluates the formula against up to 3 real funds from the DB.
    """
    vocab = body.available_variables or _ALL_METRIC_COLS

    # Load up to 3 real funds for sample preview
    rows = db.execute(text("""
        SELECT
            sm.information_ratio_3yr, sm.sharpe_ratio_3yr, sm.tracking_error_3yr,
            sm.ir_slope_6m_proxy, sm.jensens_alpha_3yr,
            sr.fund_1yr_ret, sr.fund_3yr_ret, sr.fund_5yr_ret,
            sr.active_1yr_ret, sr.active_3yr_ret, sr.active_5yr_ret,
            er.expense_ratio_pct, s.rank_delta_6m
        FROM selfmade_ranking_snapshot s
        JOIN selfmade_scheme_metrics sm ON sm.schemecode = s.schemecode
        LEFT JOIN selfmade_scheme_returns sr ON sr.schemecode = s.schemecode
        LEFT JOIN selfmade_expense_ratio er ON er.schemecode = s.schemecode
        WHERE s.snapshot_date = (SELECT MAX(snapshot_date) FROM selfmade_ranking_snapshot)
        LIMIT 3
    """)).fetchall()

    _ENV_COLS = [
        "information_ratio_3yr", "sharpe_ratio_3yr", "tracking_error_3yr",
        "ir_slope_6m_proxy", "jensens_alpha_3yr",
        "fund_1yr_ret", "fund_3yr_ret", "fund_5yr_ret",
        "active_1yr_ret", "active_3yr_ret", "active_5yr_ret",
        "expense_ratio_pct", "rank_delta_6m",
    ]
    sample_envs = [
        {col: float(r[i]) for i, col in enumerate(_ENV_COLS) if r[i] is not None}
        for r in rows
    ]

    result = validate_formula(body.formula_text, vocab, sample_envs or None)
    return result.to_dict()


# ── POST /rules/sandbox/run-v2 ────────────────────────────────────────────────

@router.post("/sandbox/run-v2")
def sandbox_run_v2(
    body: SandboxRunV2Request,
    db: Session = Depends(get_db),
) -> SandboxRunV2Response:
    """
    Re-rank funds using sandbox weights against selfmade_ tables.
    Reuses percentile_rank() from app.quant.metrics — no reimplementation.

    Returns ranked list + diff vs current default snapshot ranks.
    Validates that weights sum to 1.0 within epsilon; rejects otherwise.
    """
    components = body.rule_components
    if not components:
        raise __import__("fastapi").HTTPException(
            status_code=422, detail="rule_components must not be empty"
        )

    total_weight = sum(c.weight for c in components)
    if abs(total_weight - 1.0) > 0.005:
        raise __import__("fastapi").HTTPException(
            status_code=422,
            detail=f"Weights must sum to 1.0 (±0.5%). Current total: {total_weight:.4f}. "
                   f"Off by {abs(total_weight - 1.0) * 100:.2f} percentage points.",
        )

    # Validate metric columns
    warnings: list[str] = []
    valid_components = []
    for c in components:
        if c.metric_column not in METRIC_VOCAB:
            warnings.append(f"Unknown metric_column '{c.metric_column}' — skipped")
        else:
            valid_components.append(c)

    if not valid_components:
        raise __import__("fastapi").HTTPException(
            status_code=422, detail="No valid metric_column values in rule_components"
        )

    # Load universe
    universe = _load_universe(body.category, db)
    if not universe:
        raise __import__("fastapi").HTTPException(
            status_code=404,
            detail=f"No ranking data found for category '{body.category}'"
        )

    # Cross-sectional percentile rank per metric
    for comp in valid_components:
        col = comp.metric_column
        direction = comp.direction or METRIC_VOCAB[col]["direction"]
        vals = [(i, float(f[col])) for i, f in enumerate(universe) if f.get(col) is not None]
        universe_vals = [v for _, v in vals]
        for i, val in vals:
            universe[i][f"_pr_{col}"] = percentile_rank(val, universe_vals, direction)

    # Weighted composite score
    for f in universe:
        f["sandbox_score"] = sum(
            f.get(f"_pr_{c.metric_column}", 0.0) * c.weight
            for c in valid_components
        )

    # Build sandbox ranking
    sandbox_ranked = sorted(universe, key=lambda x: x["sandbox_score"], reverse=True)
    default_rank_map = {f["schemecode"]: f["default_rank"] for f in universe}
    sandbox_rank_map = {f["schemecode"]: i + 1 for i, f in enumerate(sandbox_ranked)}

    # Diff
    promoted = dropped = no_change = 0
    results: list[SandboxFundResult] = []
    for sb_rank, f in enumerate(sandbox_ranked, 1):
        def_rank = f["default_rank"] or sb_rank
        change = def_rank - sb_rank
        if change > 0:
            promoted += 1
        elif change < 0:
            dropped += 1
        else:
            no_change += 1
        results.append(SandboxFundResult(
            schemecode=int(f["schemecode"]),
            fund_name=str(f["fund_name"]),
            default_rank=int(def_rank),
            sandbox_rank=sb_rank,
            rank_change=change,
            default_score=round(float(f.get("default_score") or 0), 4),
            sandbox_score=round(float(f["sandbox_score"]), 4),
        ))

    # Top-10 turnover
    default_top10 = set(
        sc for sc, dr in sorted(default_rank_map.items(), key=lambda x: x[1])[:10]
    )
    sandbox_top10 = set(
        f["schemecode"] for f in sandbox_ranked[:10]
    )
    entering = [f["fund_name"] for f in sandbox_ranked[:10] if f["schemecode"] not in default_top10]
    leaving  = [
        f["fund_name"] for f in universe
        if f["schemecode"] in default_top10 and f["schemecode"] not in sandbox_top10
    ][:10]
    # Turnover = entering funds / top-10 size * 100 → 0–100% scale.
    # (entering == leaving when both ranked sets are the same size, so either works.)
    turnover = (len(entering) / 10) * 100 if default_top10 else 0.0

    return SandboxRunV2Response(
        data_version=settings.data_version,
        rule_version="sandbox",
        calculation_version="2.0",
        as_of_date=str(date.today()),
        category=body.category,
        fund_count=len(universe),
        promoted_count=promoted,
        dropped_count=dropped,
        no_change_count=no_change,
        top10_turnover_pct=round(turnover, 1),
        entering_top10=entering[:5],
        leaving_top10=leaving[:5],
        results=results,
        warnings=warnings,
    )


# ── POST /rules/submit-for-approval ──────────────────────────────────────────

@router.post("/submit-for-approval", status_code=201)
def submit_for_approval(
    body: SubmitForApprovalRequest,
    db: Session = Depends(get_db),
) -> dict:
    """
    Create a new selfmade_rule_version row with status='pending_review'.
    The row is NOT set as is_active=true — approval requires a separate action.
    Links the sandbox run summary as JSON for the Rule Approval page.
    """
    if not body.rationale or not body.rationale.strip():
        raise __import__("fastapi").HTTPException(
            status_code=422, detail="rationale must not be empty"
        )

    # Get the active rule_set_id
    rs = db.execute(text("""
        SELECT id FROM selfmade_rule_set WHERE is_active = true LIMIT 1
    """)).fetchone()
    if not rs:
        raise __import__("fastapi").HTTPException(
            status_code=500, detail="No active rule set found"
        )
    rule_set_id = rs[0]

    # Count pending versions to generate a label
    pending_count = db.execute(text("""
        SELECT COUNT(*) FROM selfmade_rule_version WHERE status = 'pending_review'
    """)).scalar() or 0

    version_label = f"sandbox-{int(pending_count) + 1}"
    now = datetime.utcnow()

    # Insert the pending version (is_active=false)
    rv = db.execute(text("""
        INSERT INTO selfmade_rule_version
          (rule_set_id, version_label, is_active, status, rationale, sandbox_run_json,
           change_note, created_at, submitted_by)
        VALUES
          (:rs_id, :label, false, 'pending_review', :rationale, :sb_json, :note, :now, :submitted_by)
        RETURNING id, version_label, status, created_at
    """), {
        "rs_id":    rule_set_id,
        "label":    version_label,
        "rationale": body.rationale.strip(),
        "sb_json":  json.dumps(body.sandbox_run_summary) if body.sandbox_run_summary else None,
        "note":     f"Sandbox submitted for approval — category: {body.category}",
        "now":      now,
        "submitted_by": body.submitted_by.strip() or "Unknown",
    }).fetchone()
    db.commit()

    rule_version_id = rv[0]

    # Insert the proposed components
    for i, comp in enumerate(body.rule_components):
        vocab_entry = METRIC_VOCAB.get(comp.metric_column, {})
        db.execute(text("""
            INSERT INTO selfmade_rule_component
              (rule_version_id, component_name, metric_column, metric_source,
               direction, weight, label_display, sort_order)
            VALUES
              (:rv_id, :name, :col, :src, :dir, :w, :label, :order)
        """), {
            "rv_id":  rule_version_id,
            "name":   vocab_entry.get("label", comp.metric_column),
            "col":    comp.metric_column,
            "src":    vocab_entry.get("source", "selfmade_scheme_metrics"),
            "dir":    comp.direction or vocab_entry.get("direction", "higher_better"),
            "w":      comp.weight,
            "label":  vocab_entry.get("label", comp.metric_column),
            "order":  i + 1,
        })
    db.commit()

    return {
        "rule_version_id": rule_version_id,
        "version_label":   rv[1],
        "status":          rv[2],
        "created_at":      rv[3].isoformat() if rv[3] else None,
        "message": (
            f"Rule version '{rv[1]}' submitted for approval. "
            "Status is 'pending_review' — it is NOT the active default until approved."
        ),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Rule Approval & Version History governance endpoints
# ═══════════════════════════════════════════════════════════════════════════════

from fastapi import HTTPException as _HTTPException


def _version_components(db: "Session", rv_id: int) -> list[dict]:
    rows = db.execute(text("""
        SELECT metric_column, weight, direction, component_name, sort_order
        FROM selfmade_rule_component WHERE rule_version_id = :rv_id
        ORDER BY sort_order
    """), {"rv_id": rv_id}).fetchall()
    return [
        {
            "metric_column":  r[0],
            "weight":         float(r[1]),
            "weight_pct":     round(float(r[1]) * 100, 1),
            "direction":      r[2],
            "component_name": r[3],
            "sort_order":     r[4],
        }
        for r in rows
    ]


def _get_active_version_row(db: "Session") -> dict | None:
    row = db.execute(text("""
        SELECT id, version_label FROM selfmade_rule_version
        WHERE is_active = true ORDER BY id DESC LIMIT 1
    """)).fetchone()
    if not row:
        return None
    return {"id": row[0], "version_label": row[1]}


def _write_audit_event(
    db: "Session",
    action: str,
    actor: str,
    rule_version_id: int,
    comment: str | None,
) -> None:
    db.execute(text("""
        INSERT INTO selfmade_audit_event (action, actor, rule_version_id, comment, created_at)
        VALUES (:action, :actor, :rv_id, :comment, NOW())
    """), {"action": action, "actor": actor, "rv_id": rule_version_id, "comment": comment})


def _live_diff(active_comps: list[dict], proposed_comps: list[dict]) -> list[dict]:
    """Compute per-component diff: current weight → proposed weight with change type."""
    active_map = {c["metric_column"]: c for c in active_comps}
    proposed_map = {c["metric_column"]: c for c in proposed_comps}
    all_metrics = sorted(set(list(active_map.keys()) + list(proposed_map.keys())))
    result = []
    for metric in all_metrics:
        old = active_map.get(metric)
        new = proposed_map.get(metric)
        old_w = old["weight"] if old else None
        new_w = new["weight"] if new else None
        name = (new or old or {}).get("component_name", metric)
        change_type = (
            "removed"   if new_w is None else
            "added"     if old_w is None else
            "changed"   if abs(new_w - old_w) > 0.0001 else
            "unchanged"
        )
        result.append({
            "metric_column":   metric,
            "component_name":  name,
            "current_weight":  old_w,
            "proposed_weight": new_w,
            "delta":           round(new_w - old_w, 4) if old_w is not None and new_w is not None else None,
            "change_type":     change_type,
        })
    return result


# ── GET /rules/pending ────────────────────────────────────────────────────────

@router.get("/pending")
def get_pending_versions(db: Session = Depends(get_db)) -> list[dict]:
    """
    All pending_review versions with a live diff against the current active version.
    The diff is always computed at request time — not frozen at submission time.
    """
    pending_rows = db.execute(text("""
        SELECT id, version_label, status, rationale, approved_by, approved_at,
               created_at, submitted_by
        FROM selfmade_rule_version
        WHERE status = 'pending_review'
        ORDER BY created_at DESC
    """)).fetchall()

    active = _get_active_version_row(db)
    active_comps = _version_components(db, active["id"]) if active else []

    result = []
    for row in pending_rows:
        rv_id, label, status, rationale, appr_by, appr_at, created_at, submitted_by = row
        proposed_comps = _version_components(db, rv_id)
        result.append({
            "rule_version_id":       rv_id,
            "version_label":         label,
            "status":                status,
            "submitted_by":          submitted_by,
            "submitted_at":          created_at.isoformat() if created_at else None,
            "rationale":             rationale,
            "active_version_label":  active["version_label"] if active else None,
            "diff":                  _live_diff(active_comps, proposed_comps),
            "components":            proposed_comps,
        })
    return result


# ── GET /rules/all-versions ───────────────────────────────────────────────────

@router.get("/all-versions")
def list_all_versions(db: Session = Depends(get_db)) -> list[dict]:
    """
    Full version timeline: every version regardless of status, newest first.
    Includes published_on (approved_at), published_by (approved_by), submitted_at (created_at).
    """
    rows = db.execute(text("""
        SELECT id, version_label, status, is_active, approved_by, approved_at,
               created_at, submitted_by, rationale, parent_version_id
        FROM selfmade_rule_version
        ORDER BY id DESC
    """)).fetchall()

    result = []
    for r in rows:
        rv_id, label, status, is_active, pub_by, pub_on, created_at, sub_by, rationale, parent_id = r
        result.append({
            "id":              rv_id,
            "version_label":   label,
            "status":          status,
            "is_current_default": bool(is_active),
            "published_by":    pub_by,
            "published_on":    pub_on.isoformat() if pub_on else None,
            "submitted_by":    sub_by,
            "submitted_at":    created_at.isoformat() if created_at else None,
            "rationale":       rationale,
            "parent_version_id": parent_id,
        })
    return result


# ── GET /rules/all-versions/{id} ─────────────────────────────────────────────

@router.get("/all-versions/{version_id}")
def get_version_detail(version_id: int, db: Session = Depends(get_db)) -> dict:
    """Single version detail: components, status, metadata, superseded_by pointer."""
    row = db.execute(text("""
        SELECT id, version_label, status, is_active, approved_by, approved_at,
               created_at, submitted_by, rationale, parent_version_id, change_note
        FROM selfmade_rule_version WHERE id = :id
    """), {"id": version_id}).fetchone()

    if not row:
        raise _HTTPException(status_code=404, detail=f"Rule version {version_id} not found")

    rv_id, label, status, is_active, pub_by, pub_on, created_at, sub_by, rationale, parent_id, note = row

    # Find which version superseded this one (if it was ever active and is now superseded)
    superseded_by = None
    if status == "superseded":
        sup_row = db.execute(text("""
            SELECT id, version_label FROM selfmade_rule_version
            WHERE approved_at > :pub_on AND (status = 'active' OR is_active = true)
            ORDER BY approved_at ASC LIMIT 1
        """), {"pub_on": pub_on or created_at}).fetchone()
        if sup_row:
            superseded_by = {"id": sup_row[0], "version_label": sup_row[1]}

    return {
        "id":                 rv_id,
        "version_label":      label,
        "status":             status,
        "is_current_default": bool(is_active),
        "published_by":       pub_by,
        "published_on":       pub_on.isoformat() if pub_on else None,
        "submitted_by":       sub_by,
        "submitted_at":       created_at.isoformat() if created_at else None,
        "rationale":          rationale,
        "change_note":        note,
        "parent_version_id":  parent_id,
        "superseded_by":      superseded_by,
        "components":         _version_components(db, rv_id),
    }


# ── Pydantic schemas for governance actions ───────────────────────────────────

class ApproveRequest(BaseModel):
    rule_version_id: int
    approver_name: str
    comment: str | None = None


class RejectRequest(BaseModel):
    rule_version_id: int
    approver_name: str
    comment: str


class RequestChangesRequest(BaseModel):
    rule_version_id: int
    approver_name: str
    comment: str


class RevertRequest(BaseModel):
    approver_name: str
    comment: str | None = None


# ── POST /rules/approve ───────────────────────────────────────────────────────

@router.post("/approve")
def approve_version(body: ApproveRequest, db: Session = Depends(get_db)) -> dict:
    """
    THE critical governance action. In one transaction:
      1. Set the target version active, status=active.
      2. Set the previously active version status=superseded (keep its row + components).
      3. Write an audit_event row.
    Returns the new active version's full detail.
    """
    if not body.approver_name or not body.approver_name.strip():
        raise _HTTPException(status_code=422, detail="approver_name must not be blank")

    target = db.execute(text("""
        SELECT id, version_label, status FROM selfmade_rule_version WHERE id = :id
    """), {"id": body.rule_version_id}).fetchone()

    if not target:
        raise _HTTPException(status_code=404, detail=f"Rule version {body.rule_version_id} not found")

    if target[2] != "pending_review":
        raise _HTTPException(
            status_code=422,
            detail=f"Version {body.rule_version_id} has status '{target[2]}'; only pending_review versions can be approved"
        )

    now = datetime.utcnow()
    approver = body.approver_name.strip()

    # Mark previous active version superseded
    db.execute(text("""
        UPDATE selfmade_rule_version
        SET is_active = false, status = 'superseded'
        WHERE is_active = true
    """))

    # Activate the target version
    db.execute(text("""
        UPDATE selfmade_rule_version
        SET is_active = true, status = 'active',
            approved_by = :approver, approved_at = :now
        WHERE id = :id
    """), {"approver": approver, "now": now, "id": body.rule_version_id})

    _write_audit_event(db, "approved", approver, body.rule_version_id, body.comment)
    db.commit()

    return get_version_detail(body.rule_version_id, db)


# ── POST /rules/reject ────────────────────────────────────────────────────────

@router.post("/reject")
def reject_version(body: RejectRequest, db: Session = Depends(get_db)) -> dict:
    """
    Mark a pending_review version as rejected. Does NOT touch the currently active version.
    Rejected versions stay permanently in history (immutable audit trail).
    """
    if not body.approver_name or not body.approver_name.strip():
        raise _HTTPException(status_code=422, detail="approver_name must not be blank")
    if not body.comment or not body.comment.strip():
        raise _HTTPException(status_code=422, detail="comment is required when rejecting")

    target = db.execute(text("""
        SELECT id, version_label, status FROM selfmade_rule_version WHERE id = :id
    """), {"id": body.rule_version_id}).fetchone()

    if not target:
        raise _HTTPException(status_code=404, detail=f"Rule version {body.rule_version_id} not found")

    if target[2] != "pending_review":
        raise _HTTPException(
            status_code=422,
            detail=f"Version {body.rule_version_id} has status '{target[2]}'; only pending_review can be rejected"
        )

    approver = body.approver_name.strip()
    db.execute(text("""
        UPDATE selfmade_rule_version
        SET status = 'rejected', approved_by = :approver, approved_at = NOW()
        WHERE id = :id
    """), {"approver": approver, "id": body.rule_version_id})

    _write_audit_event(db, "rejected", approver, body.rule_version_id, body.comment)
    db.commit()

    return get_version_detail(body.rule_version_id, db)


# ── POST /rules/request-changes ───────────────────────────────────────────────

@router.post("/request-changes")
def request_changes(body: RequestChangesRequest, db: Session = Depends(get_db)) -> dict:
    """
    Mark a pending_review version as changes_requested. Does NOT delete the version.
    If the submitter wants another attempt, they submit a NEW sandbox from Rule Playground.
    """
    if not body.approver_name or not body.approver_name.strip():
        raise _HTTPException(status_code=422, detail="approver_name must not be blank")
    if not body.comment or not body.comment.strip():
        raise _HTTPException(status_code=422, detail="comment is required when requesting changes")

    target = db.execute(text("""
        SELECT id, version_label, status FROM selfmade_rule_version WHERE id = :id
    """), {"id": body.rule_version_id}).fetchone()

    if not target:
        raise _HTTPException(status_code=404, detail=f"Rule version {body.rule_version_id} not found")

    if target[2] != "pending_review":
        raise _HTTPException(
            status_code=422,
            detail=f"Version {body.rule_version_id} has status '{target[2]}'; only pending_review can have changes requested"
        )

    approver = body.approver_name.strip()
    db.execute(text("""
        UPDATE selfmade_rule_version
        SET status = 'changes_requested', approved_by = :approver, approved_at = NOW()
        WHERE id = :id
    """), {"approver": approver, "id": body.rule_version_id})

    _write_audit_event(db, "changes_requested", approver, body.rule_version_id, body.comment)
    db.commit()

    return get_version_detail(body.rule_version_id, db)


# ── POST /rules/all-versions/{id}/revert ─────────────────────────────────────

@router.post("/all-versions/{version_id}/revert")
def revert_to_version(
    version_id: int,
    body: RevertRequest,
    db: Session = Depends(get_db),
) -> dict:
    """
    Create a NEW version row copying the target version's components exactly, then activate it.
    The old version row is NEVER modified (immutability). The currently active version is
    set to superseded. Returns the new version's full detail.
    """
    if not body.approver_name or not body.approver_name.strip():
        raise _HTTPException(status_code=422, detail="approver_name must not be blank")

    target = db.execute(text("""
        SELECT id, version_label, rule_set_id FROM selfmade_rule_version WHERE id = :id
    """), {"id": version_id}).fetchone()

    if not target:
        raise _HTTPException(status_code=404, detail=f"Rule version {version_id} not found")

    # Disallow reverting to yourself (i.e., the currently active version)
    active = _get_active_version_row(db)
    if active and active["id"] == version_id:
        raise _HTTPException(
            status_code=422,
            detail="Cannot revert to the currently active version"
        )

    approver = body.approver_name.strip()
    now = datetime.utcnow()
    source_label = target[1]
    rule_set_id = target[2]

    # New label: revert-to-<source_label>
    new_label = f"reverted-to-{source_label}"
    # Make label unique if it already exists
    existing = db.execute(text(
        "SELECT COUNT(*) FROM selfmade_rule_version WHERE version_label LIKE :pattern"
    ), {"pattern": f"{new_label}%"}).scalar() or 0
    if existing > 0:
        new_label = f"{new_label}-{int(existing) + 1}"

    # Supersede the current active version
    db.execute(text("""
        UPDATE selfmade_rule_version
        SET is_active = false, status = 'superseded'
        WHERE is_active = true
    """))

    # Create the new reverted version
    new_rv = db.execute(text("""
        INSERT INTO selfmade_rule_version
          (rule_set_id, version_label, is_active, status, approved_by, approved_at,
           change_note, created_at, submitted_by, parent_version_id)
        VALUES
          (:rs_id, :label, true, 'active', :approver, :now,
           :note, :now, :approver, :parent_id)
        RETURNING id
    """), {
        "rs_id":     rule_set_id,
        "label":     new_label,
        "approver":  approver,
        "now":       now,
        "note":      f"Reverted to content of version '{source_label}' (id={version_id})",
        "parent_id": version_id,
    }).fetchone()
    new_rv_id = new_rv[0]

    # Copy all components from the source version to the new one
    source_comps = db.execute(text("""
        SELECT component_name, metric_column, metric_source, direction, weight,
               label_display, sort_order
        FROM selfmade_rule_component WHERE rule_version_id = :rv_id
        ORDER BY sort_order
    """), {"rv_id": version_id}).fetchall()

    for comp in source_comps:
        db.execute(text("""
            INSERT INTO selfmade_rule_component
              (rule_version_id, component_name, metric_column, metric_source,
               direction, weight, label_display, sort_order)
            VALUES (:rv_id, :name, :col, :src, :dir, :w, :label, :order)
        """), {
            "rv_id":  new_rv_id,
            "name":   comp[0],
            "col":    comp[1],
            "src":    comp[2],
            "dir":    comp[3],
            "w":      comp[4],
            "label":  comp[5],
            "order":  comp[6],
        })

    _write_audit_event(
        db, "reverted", approver, new_rv_id,
        f"Reverted to '{source_label}' (source id={version_id}). {body.comment or ''}"
    )
    db.commit()

    return get_version_detail(new_rv_id, db)
