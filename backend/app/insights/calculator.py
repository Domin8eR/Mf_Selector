"""
Helper functions that compute insight variables from DB.

All functions take a SQLAlchemy Session and return structured dicts
for template rendering. Never calls an LLM.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.quant.metrics import active_share as _active_share_fn
from app.quant.metrics import portfolio_stability as _portfolio_stability_fn


def get_holdings_metrics(db: Session, schemecodes: list[int]) -> dict:
    """Top 5 holdings, concentration, sector breakdown, sectors_to_80 for each fund."""
    result = {}
    for sc in schemecodes:
        rows = db.execute(text("""
            SELECT compname, holdpercentage, sect_name
            FROM accord_fintech_mf_portfolio
            WHERE schemecode = :sc
              AND invdate = (
                  SELECT MAX(invdate) FROM accord_fintech_mf_portfolio
                  WHERE schemecode = :sc
              )
            ORDER BY holdpercentage DESC NULLS LAST
        """), {"sc": sc}).fetchall()

        if not rows:
            result[sc] = {
                "top5_names": "N/A",
                "top5_pct": 0.0,
                "concentration_label": "No holdings data available",
                "top3_sectors": "N/A",
                "sectors_to_80": 0,
                "sector_label": "No sector data available",
                "sector_breakdown": [],
            }
            continue

        top5 = rows[:5]
        top5_pct = sum(float(r[1] or 0) for r in top5)
        top5_names = ", ".join(r[0] or "Unknown" for r in top5)

        if top5_pct >= 35:
            conc_label = "High concentration — top 5 holdings dominate the portfolio"
        elif top5_pct >= 20:
            conc_label = "Moderate concentration in top holdings"
        else:
            conc_label = "Well-diversified across holdings"

        # Sector aggregation
        sector_map: dict[str, float] = {}
        for r in rows:
            s = r[2] or "Other"
            sector_map[s] = sector_map.get(s, 0) + float(r[1] or 0)

        sorted_sectors = sorted(sector_map.items(), key=lambda x: x[1], reverse=True)
        top3_sectors = ", ".join(f"{s[0]} ({s[1]:.1f}%)" for s in sorted_sectors[:3])

        cumulative = 0.0
        sectors_to_80 = 0
        for _, pct in sorted_sectors:
            cumulative += pct
            sectors_to_80 += 1
            if cumulative >= 80:
                break

        if sectors_to_80 <= 3:
            sector_label = "Concentrated sector exposure — fewer than 4 sectors to 80%"
        elif sectors_to_80 <= 5:
            sector_label = "Moderate sector diversification"
        else:
            sector_label = "Well-diversified across sectors"

        result[sc] = {
            "top5_names": top5_names,
            "top5_pct": top5_pct,
            "concentration_label": conc_label,
            "top3_sectors": top3_sectors,
            "sectors_to_80": sectors_to_80,
            "sector_label": sector_label,
            "sector_breakdown": sorted_sectors,
        }

    return result


def get_overlap_metrics(db: Session, schemecodes: list[int]) -> dict:
    """
    Weighted overlap, Jaccard, sector overlap, common/unique holdings.

    Preferred data source: selfmade_portfolio_holding (most recent as_of_date).
    Falls back to accord_fintech_mf_portfolio if selfmade has no data.

    Returns extra fields:
      pairs: [{fund_a, fund_b, weighted_overlap, common_count}] — pairwise
      common_holdings_detail: [{security_name, sector, weights: {sc: pct}}]
                               for securities common to ALL funds
    """
    if len(schemecodes) < 2:
        return {
            "weighted_overlap": 0.0, "jaccard": 0.0, "sector_overlap": 0.0,
            "common_count": 0, "unique_count": 0, "common_to_all_count": 0,
            "overlap_label": "Need at least 2 funds to compare",
            "sector_commentary": "",
            "pairs": [],
            "common_holdings_detail": [],
        }

    # ── Load from selfmade_portfolio_holding ──────────────────────────────────
    # holdings_by_fund: {sc: {security_id(str): weight}}
    # sectors_by_fund:  {sc: {sector: weight}}
    # sec_info: {security_id(str): {"name": ..., "sector": ...}}

    holdings_by_fund: dict[int, dict[str, float]] = {}
    sectors_by_fund: dict[int, dict[str, float]] = {}
    sec_info: dict[str, dict] = {}

    for sc in schemecodes:
        rows = db.execute(text("""
            SELECT sm.company_name, sm.sector, ph.holding_weight_pct, sm.id::text AS sec_key
            FROM selfmade_portfolio_holding ph
            JOIN selfmade_security_master sm ON sm.id = ph.security_id
            WHERE ph.scheme_id = :sc AND ph.as_of_date = (
                SELECT MAX(as_of_date) FROM selfmade_portfolio_holding WHERE scheme_id = :sc
            )
            ORDER BY ph.holding_weight_pct DESC
        """), {"sc": sc}).fetchall()

        if not rows:
            # Fallback to accord_fintech_mf_portfolio
            rows_vendor = db.execute(text("""
                SELECT compname, sect_name, holdpercentage, compname AS sec_key
                FROM accord_fintech_mf_portfolio
                WHERE schemecode = :sc
                  AND invdate = (
                      SELECT MAX(invdate) FROM accord_fintech_mf_portfolio WHERE schemecode = :sc
                  )
            """), {"sc": sc}).fetchall()
            h: dict[str, float] = {}
            s: dict[str, float] = {}
            for r in rows_vendor:
                key = (r[0] or "Unknown").strip().lower()
                pct = float(r[2] or 0)
                h[key] = h.get(key, 0) + pct
                sect = (r[1] or "Other").strip()
                s[sect] = s.get(sect, 0) + pct
                if key not in sec_info:
                    sec_info[key] = {"name": r[0] or "Unknown", "sector": r[1] or "Other"}
            holdings_by_fund[sc] = h
            sectors_by_fund[sc] = s
        else:
            h = {}
            s = {}
            for r in rows:
                name, sector, wt, sec_key = r[0], r[1], float(r[2] or 0), str(r[3])
                h[sec_key] = h.get(sec_key, 0) + wt
                sect = (sector or "Other").strip()
                s[sect] = s.get(sect, 0) + wt
                if sec_key not in sec_info:
                    sec_info[sec_key] = {"name": name or "Unknown", "sector": sect}
            holdings_by_fund[sc] = h
            sectors_by_fund[sc] = s

    # ── Union / intersection ──────────────────────────────────────────────────
    all_holdings: set[str] = set()
    for h in holdings_by_fund.values():
        all_holdings.update(h.keys())

    common_to_all = all_holdings.copy()
    for h in holdings_by_fund.values():
        common_to_all &= set(h.keys())

    # ── Pairwise weighted overlap ─────────────────────────────────────────────
    fund_list = list(holdings_by_fund.keys())
    pair_overlaps: list[float] = []
    pairs_detail: list[dict] = []

    for i in range(len(fund_list)):
        for j in range(i + 1, len(fund_list)):
            fa, fb = fund_list[i], fund_list[j]
            h1, h2 = holdings_by_fund[fa], holdings_by_fund[fb]
            common = set(h1.keys()) & set(h2.keys())
            w_overlap = sum(min(h1[c], h2[c]) for c in common)
            pair_overlaps.append(w_overlap)
            pairs_detail.append({
                "fund_a": fa,
                "fund_b": fb,
                "weighted_overlap": round(w_overlap, 4),
                "common_count": len(common),
            })

    weighted_overlap = sum(pair_overlaps) / len(pair_overlaps) if pair_overlaps else 0.0

    # ── Jaccard ───────────────────────────────────────────────────────────────
    pairwise_jaccards: list[float] = []
    for i in range(len(fund_list)):
        for j in range(i + 1, len(fund_list)):
            s1 = set(holdings_by_fund[fund_list[i]].keys())
            s2 = set(holdings_by_fund[fund_list[j]].keys())
            union = s1 | s2
            inter = s1 & s2
            pairwise_jaccards.append(len(inter) / len(union) * 100 if union else 0.0)
    jaccard = sum(pairwise_jaccards) / len(pairwise_jaccards) if pairwise_jaccards else 0.0

    # ── Sector overlap ────────────────────────────────────────────────────────
    all_sectors: set[str] = set()
    for sv in sectors_by_fund.values():
        all_sectors.update(sv.keys())
    common_sectors: set[str] = all_sectors.copy()
    for sv in sectors_by_fund.values():
        common_sectors &= set(sv.keys())

    sector_pcts: list[float] = []
    for sc in schemecodes:
        total_s = sum(sectors_by_fund.get(sc, {}).get(sect, 0.0) for sect in common_sectors)
        sector_pcts.append(total_s)
    sector_overlap = sum(sector_pcts) / len(sector_pcts) if sector_pcts else 0.0

    # ── Labels ────────────────────────────────────────────────────────────────
    if weighted_overlap >= 70:
        overlap_label = "Very high overlap — these funds are highly similar"
    elif weighted_overlap >= 50:
        overlap_label = "High overlap — significant portfolio commonality"
    elif weighted_overlap >= 30:
        overlap_label = "Moderate overlap — some diversification benefit"
    else:
        overlap_label = "Low overlap — good diversification potential"

    sector_commentary = (
        f"{len(common_sectors)} sectors common to all funds"
        if common_sectors else "Limited sector commonality"
    )

    # ── Common holdings detail (securities common to ALL funds) ───────────────
    common_holdings_detail: list[dict] = []
    for sec_key in common_to_all:
        info = sec_info.get(sec_key, {"name": sec_key, "sector": "Unknown"})
        weights_per_fund = {sc: round(holdings_by_fund[sc].get(sec_key, 0.0), 4) for sc in schemecodes}
        common_holdings_detail.append({
            "security_name": info["name"],
            "sector": info["sector"],
            "weights": weights_per_fund,
        })
    # Sort by average weight descending
    common_holdings_detail.sort(
        key=lambda x: sum(x["weights"].values()) / max(len(x["weights"]), 1),
        reverse=True,
    )

    return {
        "weighted_overlap": round(weighted_overlap, 4),
        "jaccard": round(jaccard, 4),
        "sector_overlap": round(sector_overlap, 4),
        "common_count": len(common_to_all),
        "unique_count": len(all_holdings),
        "common_to_all_count": len(common_to_all),
        "overlap_label": overlap_label,
        "common_sectors": len(common_sectors),
        "sector_commentary": sector_commentary,
        "pairs": pairs_detail,
        "common_holdings_detail": common_holdings_detail,
    }


def get_rank_movement(
    db: Session, schemecode: int,
) -> dict:
    """Return rank delta and movement info for a scheme."""
    row = db.execute(text("""
        SELECT rank_in_category, rank_in_category_prev, rank_delta,
               total_in_category, composite_score, category, amfi_name
        FROM selfmade_scheme_ranking
        WHERE schemecode = :sc
    """), {"sc": schemecode}).fetchone()

    if not row:
        return {"has_data": False}

    return {
        "has_data": True,
        "current_rank": row[0],
        "prev_rank": row[1],
        "rank_delta": row[2],
        "total_in_category": row[3],
        "composite_score": float(row[4]) if row[4] else 0,
        "category": row[5],
        "fund_name": row[6],
    }


def compute_ir_slope_proxy(db: Session, schemecode: int) -> float | None:
    """
    OLS slope of monthly IR from ratio_3year_monthlyret, last 12 months.
    Returns slope per month. NULL if < 6 observations.
    """
    rows = db.execute(text("""
        SELECT ratiodate, informationratio
        FROM ratio_3year_monthlyret
        WHERE schemecode = :sc
          AND informationratio IS NOT NULL
        ORDER BY ratiodate DESC
        LIMIT 12
    """), {"sc": schemecode}).fetchall()

    if len(rows) < 6:
        return None

    rows = list(reversed(rows))
    n = len(rows)
    x_vals = list(range(n))
    y_vals = [float(r[1]) for r in rows]

    x_mean = sum(x_vals) / n
    y_mean = sum(y_vals) / n

    num = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_vals, y_vals))
    den = sum((x - x_mean) ** 2 for x in x_vals)

    if den == 0:
        return None

    return num / den


def compute_improvement_metric(db: Session, schemecode: int) -> float | None:
    """
    recent_avg_ir (last 3 months) - prior_avg_ir (months 4-6).
    NULL if insufficient data.
    """
    rows = db.execute(text("""
        SELECT informationratio
        FROM ratio_3year_monthlyret
        WHERE schemecode = :sc
          AND informationratio IS NOT NULL
        ORDER BY ratiodate DESC
        LIMIT 6
    """), {"sc": schemecode}).fetchall()

    if len(rows) < 6:
        return None

    recent = [float(r[0]) for r in rows[:3]]
    prior = [float(r[0]) for r in rows[3:6]]

    return sum(recent) / 3 - sum(prior) / 3


def compute_outperformance_ratio(db: Session, schemecode: int) -> float | None:
    """
    Months where fund return exceeded benchmark / total months, as percentage.
    Uses ratio_3year_monthlyret. NULL if < 6 observations.
    """
    rows = db.execute(text("""
        SELECT average_nav, avgindex
        FROM ratio_3year_monthlyret
        WHERE schemecode = :sc
          AND average_nav IS NOT NULL
          AND avgindex IS NOT NULL
    """), {"sc": schemecode}).fetchall()

    if len(rows) < 6:
        return None

    outperformed = sum(1 for r in rows if float(r[0]) > float(r[1]))
    return (outperformed / len(rows)) * 100


# ══════════════════════════════════════════════════════════════════════════════
# New functions for Fund Comparison milestone
# ══════════════════════════════════════════════════════════════════════════════

def get_active_share_for_fund(db: Session, schemecode: int) -> dict:
    """
    Compute Active Share using selfmade_portfolio_holding vs selfmade_benchmark_holding.

    Active Share = 0.5 * sum(|w_fund_i - w_bm_i|) over the union of all securities.
    Keys are company_name strings (normalized). Returns percent (0-100).
    """
    # Get fund's benchmark index
    bm_row = db.execute(text("""
        SELECT benchmark_index FROM selfmade_scheme_category_benchmark
        WHERE schemecode = :sc ORDER BY valid_from DESC LIMIT 1
    """), {"sc": schemecode}).fetchone()

    if not bm_row:
        return {"value": None, "status": "insufficient_data", "confidence": "insufficient_data"}

    bm_idx = bm_row[0]

    # Get fund's current holdings as {company_name: weight_pct}
    fund_rows = db.execute(text("""
        SELECT sm.company_name, ph.holding_weight_pct
        FROM selfmade_portfolio_holding ph
        JOIN selfmade_security_master sm ON sm.id = ph.security_id
        WHERE ph.scheme_id = :sc AND ph.as_of_date = (
            SELECT MAX(as_of_date) FROM selfmade_portfolio_holding WHERE scheme_id = :sc
        )
    """), {"sc": schemecode}).fetchall()

    if not fund_rows:
        return {"value": None, "status": "insufficient_data", "confidence": "insufficient_data"}

    fund_weights: dict[str, float] = {}
    for name, wt in fund_rows:
        key = (name or "Unknown").strip().lower()
        fund_weights[key] = fund_weights.get(key, 0.0) + float(wt or 0)

    # Get benchmark holdings as {company_name: weight_pct}
    bm_rows = db.execute(text("""
        SELECT sm.company_name, bh.weight_pct
        FROM selfmade_benchmark_holding bh
        JOIN selfmade_security_master sm ON sm.id = bh.security_id
        WHERE bh.benchmark_index = :bm
    """), {"bm": bm_idx}).fetchall()

    if not bm_rows:
        return {"value": None, "status": "insufficient_data", "confidence": "insufficient_data"}

    bm_weights: dict[str, float] = {}
    for name, wt in bm_rows:
        key = (name or "Unknown").strip().lower()
        bm_weights[key] = bm_weights.get(key, 0.0) + float(wt or 0)

    result = _active_share_fn(fund_weights, bm_weights)
    if result["status"] == "ok":
        result["confidence"] = "medium"
    else:
        result["confidence"] = "insufficient_data"
    return result


def get_portfolio_stability_for_fund(db: Session, schemecode: int) -> dict:
    """
    Compute Portfolio Stability as weighted_overlap between current and historical holdings.

    Uses selfmade_portfolio_holding.
    Current  = most recent as_of_date.
    Historical = most recent date that is at least 6 months before the current date.
    Returns percent (0-100): higher = more stable.
    """
    from datetime import timedelta

    # Current date
    cur_date_row = db.execute(text("""
        SELECT MAX(as_of_date) FROM selfmade_portfolio_holding WHERE scheme_id = :sc
    """), {"sc": schemecode}).fetchone()

    if not cur_date_row or cur_date_row[0] is None:
        return {"value": None, "status": "insufficient_data", "confidence": "insufficient_data"}

    cur_date = cur_date_row[0]
    hist_cutoff = cur_date - timedelta(days=180)

    # Historical date: most recent before hist_cutoff
    hist_date_row = db.execute(text("""
        SELECT MAX(as_of_date) FROM selfmade_portfolio_holding
        WHERE scheme_id = :sc AND as_of_date <= :cutoff
    """), {"sc": schemecode, "cutoff": hist_cutoff}).fetchone()

    if not hist_date_row or hist_date_row[0] is None:
        return {"value": None, "status": "insufficient_data", "confidence": "insufficient_data"}

    hist_date = hist_date_row[0]

    # Load current holdings
    cur_rows = db.execute(text("""
        SELECT sm.company_name, ph.holding_weight_pct
        FROM selfmade_portfolio_holding ph
        JOIN selfmade_security_master sm ON sm.id = ph.security_id
        WHERE ph.scheme_id = :sc AND ph.as_of_date = :dt
    """), {"sc": schemecode, "dt": cur_date}).fetchall()

    # Load historical holdings
    hist_rows = db.execute(text("""
        SELECT sm.company_name, ph.holding_weight_pct
        FROM selfmade_portfolio_holding ph
        JOIN selfmade_security_master sm ON sm.id = ph.security_id
        WHERE ph.scheme_id = :sc AND ph.as_of_date = :dt
    """), {"sc": schemecode, "dt": hist_date}).fetchall()

    if not cur_rows or not hist_rows:
        return {"value": None, "status": "insufficient_data", "confidence": "insufficient_data"}

    def _to_weight_dict(rows: list) -> dict[str, float]:
        d: dict[str, float] = {}
        for name, wt in rows:
            key = (name or "Unknown").strip().lower()
            d[key] = d.get(key, 0.0) + float(wt or 0)
        return d

    current_weights = _to_weight_dict(cur_rows)
    historical_weights = _to_weight_dict(hist_rows)

    result = _portfolio_stability_fn(current_weights, historical_weights)
    if result["status"] == "ok":
        result["confidence"] = "medium"
    else:
        result["confidence"] = "insufficient_data"
    return result


def get_expense_ratio_for_fund(db: Session, schemecode: int) -> dict:
    """
    Get expense ratio from selfmade_expense_ratio.
    Falls back to expenceratio vendor table if not found.
    """
    row = db.execute(text("""
        SELECT expense_ratio_pct FROM selfmade_expense_ratio WHERE schemecode = :sc
    """), {"sc": schemecode}).fetchone()

    if row:
        return {"value": float(row[0]), "status": "ok"}

    # Fallback to vendor table
    vendor_row = db.execute(text("""
        SELECT expratio FROM expenceratio
        WHERE schemecode = :sc AND flag = 'A'
        ORDER BY date DESC LIMIT 1
    """), {"sc": schemecode}).fetchone()

    if vendor_row and vendor_row[0] is not None:
        return {"value": float(vendor_row[0]), "status": "ok"}

    return {"value": None, "status": "insufficient_data"}


def get_sector_overlap_table(db: Session, schemecodes: list[int]) -> list[dict]:
    """
    Per-sector weight for each fund + min(weights) = overlap for each sector.
    Returns list of {sector, weights: {sc: pct}, overlap: min(weights)}.
    Uses selfmade_portfolio_holding + selfmade_security_master.
    """
    # Load sector weights per fund
    sectors_by_fund: dict[int, dict[str, float]] = {}

    for sc in schemecodes:
        rows = db.execute(text("""
            SELECT sm.sector, SUM(ph.holding_weight_pct) AS sector_wt
            FROM selfmade_portfolio_holding ph
            JOIN selfmade_security_master sm ON sm.id = ph.security_id
            WHERE ph.scheme_id = :sc AND ph.as_of_date = (
                SELECT MAX(as_of_date) FROM selfmade_portfolio_holding WHERE scheme_id = :sc
            )
            AND sm.sector IS NOT NULL
            GROUP BY sm.sector
        """), {"sc": sc}).fetchall()

        sectors_by_fund[sc] = {r[0]: float(r[1] or 0) for r in rows}

    # Collect all sectors
    all_sectors: set[str] = set()
    for sv in sectors_by_fund.values():
        all_sectors.update(sv.keys())

    result: list[dict] = []
    for sector in sorted(all_sectors):
        weights_per_fund = {sc: round(sectors_by_fund.get(sc, {}).get(sector, 0.0), 4)
                            for sc in schemecodes}
        non_zero = [w for w in weights_per_fund.values() if w > 0]
        overlap = round(min(weights_per_fund.values()), 4) if non_zero else 0.0
        result.append({
            "sector": sector,
            "weights": weights_per_fund,
            "overlap": overlap,
        })

    # Sort by total weight descending
    result.sort(key=lambda x: sum(x["weights"].values()), reverse=True)
    return result


def get_common_holdings_table(db: Session, sc_a: int, sc_b: int) -> list[dict]:
    """
    Holdings common to both funds with weight in each. Top 20 by combined weight.
    Returns list of {security_name, sector, weight_a, weight_b, min_weight}.
    Uses selfmade_portfolio_holding + selfmade_security_master.
    """
    query = text("""
        SELECT
            sm.company_name,
            sm.sector,
            ph.holding_weight_pct,
            ph.scheme_id
        FROM selfmade_portfolio_holding ph
        JOIN selfmade_security_master sm ON sm.id = ph.security_id
        WHERE ph.scheme_id = ANY(:codes)
          AND ph.as_of_date = (
              SELECT MAX(as_of_date) FROM selfmade_portfolio_holding WHERE scheme_id = ph.scheme_id
          )
    """)
    rows = db.execute(query, {"codes": [sc_a, sc_b]}).fetchall()

    # Group by security
    by_sec: dict[str, dict] = {}
    for name, sector, wt, sc in rows:
        key = (name or "Unknown").strip().lower()
        if key not in by_sec:
            by_sec[key] = {"security_name": name or "Unknown", "sector": sector or "Other",
                           "weight_a": 0.0, "weight_b": 0.0}
        if sc == sc_a:
            by_sec[key]["weight_a"] += float(wt or 0)
        elif sc == sc_b:
            by_sec[key]["weight_b"] += float(wt or 0)

    # Keep only securities present in both
    common = [
        {
            "security_name": v["security_name"],
            "sector": v["sector"],
            "weight_a": round(v["weight_a"], 4),
            "weight_b": round(v["weight_b"], 4),
            "min_weight": round(min(v["weight_a"], v["weight_b"]), 4),
        }
        for v in by_sec.values()
        if v["weight_a"] > 0 and v["weight_b"] > 0
    ]

    # Sort by combined weight descending, top 20
    common.sort(key=lambda x: x["weight_a"] + x["weight_b"], reverse=True)
    return common[:20]
