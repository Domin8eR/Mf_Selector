"""
nav_helpers.py — Shared NAV interpolation utilities.

Extracted from app/routers/metrics.py so the compare router can import them
without circular imports.  Also kept verbatim in metrics.py.
"""

from __future__ import annotations

import math
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session


def _get_bm_tri_at(db: Session, bm_idx: str, target_date: date) -> float | None:
    """Return most-recent benchmark TRI on or before target_date."""
    row = db.execute(text("""
        SELECT tri FROM selfmade_index_returns
        WHERE index_name = :nm AND date <= :dt
        ORDER BY date DESC LIMIT 1
    """), {"nm": bm_idx, "dt": target_date}).fetchone()
    return float(row[0]) if row else None


def _interpolate_nav(target_date: date, anchors: list[tuple[date, float]]) -> float | None:
    """
    Piecewise exponential interpolation (or extrapolation) of fund NAV.
    anchors: sorted list of (date, nav) pairs.
    """
    if not anchors:
        return None
    for i in range(len(anchors) - 1):
        a_date, a_nav = anchors[i]
        b_date, b_nav = anchors[i + 1]
        if a_date <= target_date <= b_date:
            span = (b_date - a_date).days
            elapsed = (target_date - a_date).days
            if span == 0 or a_nav <= 0:
                return a_nav
            return a_nav * math.exp(math.log(b_nav / a_nav) * elapsed / span)
    # Extrapolate backward from first segment
    if target_date < anchors[0][0] and len(anchors) >= 2:
        a_date, a_nav = anchors[0]
        b_date, b_nav = anchors[1]
        span = (b_date - a_date).days
        back = (a_date - target_date).days
        if span > 0 and a_nav > 0:
            return a_nav * math.exp(math.log(b_nav / a_nav) / span * (-back))
    # Extrapolate forward from last segment
    if target_date > anchors[-1][0] and len(anchors) >= 2:
        a_date, a_nav = anchors[-2]
        b_date, b_nav = anchors[-1]
        span = (b_date - a_date).days
        fwd = (target_date - b_date).days
        if span > 0 and a_nav > 0:
            return b_nav * math.exp(math.log(b_nav / a_nav) / span * fwd)
    return anchors[-1][1]


def _build_nav_anchors(af_row: tuple | None, period: str) -> list[tuple[date, float]]:
    """
    Build a sorted list of (date, nav) anchor points from accord_fintech_mf_returns row.
    Columns: c_date, c_nav, 1yrdate, 1yrnav, 2yrdate, 2yrnav, 3yrdate, 3yrnav,
             5yrdate (idx 8), 5yrnav (idx 9).
    """
    if not af_row:
        return []
    date_nav_cols = [(6, 7), (4, 5), (2, 3), (0, 1)]  # 3yr, 2yr, 1yr, current
    if period in ("5Y", "Max") and len(af_row) > 9 and af_row[8] and af_row[9]:
        date_nav_cols = [(8, 9)] + date_nav_cols
    anchors = []
    for dc, nc in date_nav_cols:
        if af_row[dc] and af_row[nc]:
            d = af_row[dc] if isinstance(af_row[dc], date) else af_row[dc].date()
            anchors.append((d, float(af_row[nc])))
    anchors.sort()
    return anchors
