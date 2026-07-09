"""Alerts endpoint — GET /alerts.

Returns system-level alerts (data staleness, DQ flags, etc.).
Currently returns an empty list — alerting logic will be added when
the monitoring and governance modules are built.
"""

from datetime import date

from fastapi import APIRouter

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("")
def list_alerts() -> dict:
    """
    Return active system alerts.
    Shape is stable so the Home page can render an empty state or alert badges.
    """
    return {
        "alerts": [],
        "total": 0,
        "as_of_date": str(date.today()),
        "data_version": "0",
    }
