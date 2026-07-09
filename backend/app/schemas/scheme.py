"""Pydantic schemas for scheme (fund master) endpoints."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class SchemeRead(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    fund_name: str
    amc_name: str
    category: str
    benchmark_id: str | None
    plan_type: str
    option_type: str
    launch_date: date | None
    aum_cr: Decimal | None
    expense_ratio_pct: Decimal | None
    is_active: bool


class SchemePage(BaseModel):
    items: list[SchemeRead]
    total: int
    page: int
    page_size: int
