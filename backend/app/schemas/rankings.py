"""Pydantic schemas for ranking endpoints."""

from datetime import date

from pydantic import BaseModel, Field

from app.schemas.base import VersionedResponse


class ComponentContributionOut(BaseModel):
    metric_id: str
    raw_value: float | None
    normalized_value: float | None
    weight: float | None
    contribution: float | None


class RankingResultOut(BaseModel):
    """One fund in a category ranking result.

    Field names reflect what the data actually is.  The sort basis
    (currently Sharpe) is declared on the parent RankingResponse so
    callers never have to guess what the score represents.
    """

    model_config = {"from_attributes": True}

    rank: int
    scheme_plan_id: str
    fund_name: str
    amc_name: str
    score: float
    prev_rank: int | None
    rank_change: int | None
    status_label: str | None
    # Metric columns — named after the actual value they carry
    sharpe: float | None = None
    alpha: float | None = None
    beta: float | None = None
    sortino: float | None = None
    ret_1y: float | None = None   # 1-year CAGR return %
    ret_3y: float | None = None   # 3-year CAGR return %
    ret_5y: float | None = None   # 5-year CAGR return %
    aum_cr: float | None = None


class RankingResponse(VersionedResponse):
    category: str
    evaluation_date: date
    rule_set_id: str
    rule_version_id: str
    run_id: str
    # Declares which field drives the sort so callers don't have to guess.
    # "SHARPE_DESC" until informationratio is populated in mf_ratios_defaultbm.
    sort_basis: str = Field(
        default="SHARPE_DESC",
        description="Metric used to rank funds. SHARPE_DESC = Sharpe ratio descending.",
    )
    results: list[RankingResultOut]
