"""Pydantic schemas for metrics endpoints."""

from datetime import date

from pydantic import BaseModel

from app.schemas.base import VersionedResponse


class RollingIRPoint(BaseModel):
    date: date
    value: float | None


class MetricCard(BaseModel):
    metric_id: str
    label: str
    value: float | None
    formatted: str
    status: str
    confidence: str
    direction: str


class FundSummaryResponse(VersionedResponse):
    scheme_plan_id: str
    fund_name: str
    amc_name: str
    category: str
    benchmark_id: str | None
    aum_cr: float | None
    expense_ratio_pct: float | None
    launch_date: date | None
    metrics: list[MetricCard]


class RollingIRResponse(VersionedResponse):
    scheme_plan_id: str
    metric_id: str
    window_years: int
    series: list[RollingIRPoint]
