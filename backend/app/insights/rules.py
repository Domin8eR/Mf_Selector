"""
InsightRuleEngine — evaluates templates against DB state and returns
triggered template_ids + variables for rendering.
"""

from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.insights.calculator import (
    compute_improvement_metric,
    compute_ir_slope_proxy,
    get_holdings_metrics,
    get_overlap_metrics,
    get_rank_movement,
)

# Global thresholds (match spec Section 5)
IR_PERCENTILE_STRONG = 70
IR_PERCENTILE_WEAK = 40
SORTINO_PERCENTILE_STRONG = 70
SORTINO_PERCENTILE_WEAK = 40
DOWNSIDE_CAPTURE_STRONG = 85
DOWNSIDE_CAPTURE_WEAK = 105
OUTPERFORMANCE_RATIO_STRONG = 60
OUTPERFORMANCE_RATIO_WEAK = 45
IR_SLOPE_IMPROVING = 0.03
IR_SLOPE_WEAKENING = -0.03
RANK_IMPROVEMENT_THRESHOLD = 3
TOP_5_CONCENTRATION_HIGH = 35
TOP_5_CONCENTRATION_MODERATE = 20
SECTORS_TO_80_CONCENTRATED = 3
SECTORS_TO_80_MODERATE = 5
HOLDINGS_OVERLAP_VERY_HIGH = 70
HOLDINGS_OVERLAP_HIGH = 50
HOLDINGS_OVERLAP_MODERATE = 30
SCORE_TIGHT_CLUSTER_THRESHOLD = 5
IR_GAP_CLEAR_THRESHOLD = 0.10
CHURN_WARNING_THRESHOLD = 40
SHORT_WINDOW_WEIGHT_THRESHOLD = 50
RETURN_HEAVY_THRESHOLD = 50
SCORE_LEADER_GAP_THRESHOLD = 5


class InsightRuleEngine:

    def __init__(self, db: Session):
        self.db = db

    def generate_workspace_daily_briefing_insights(
        self, category_name: str, evaluation_date: date,
    ) -> list[dict]:
        """
        Workspace daily briefing — uses AIW_*_V1 templates (Section 12.6).
        Improver definition: rank_delta <= -3 AND current_rank <= 30.
        Reads from selfmade_ranking_snapshot (two most recent snapshots per category).
        Writes insight_snapshot rows via the caller (router).
        """
        results: list[dict] = []

        # ── Check snapshot availability ───────────────────────────────────────
        snapshot_dates = self.db.execute(text("""
            SELECT DISTINCT snapshot_date
            FROM selfmade_ranking_snapshot
            WHERE category = :cat
            ORDER BY snapshot_date DESC
            LIMIT 2
        """), {"cat": category_name}).fetchall()

        if len(snapshot_dates) < 2:
            # No previous snapshot — emit SNAPSHOT_MISSING templates
            results.append({
                "template_id": "AIW_RANK_IMPROVERS_COUNT_SNAPSHOT_MISSING_V1",
                "variables": {"category": category_name},
            })
            results.append({
                "template_id": "AIW_BIGGEST_RANK_IMPROVER_SNAPSHOT_MISSING_V1",
                "variables": {"category": category_name},
            })
            return results

        current_date = snapshot_dates[0][0]
        prev_date = snapshot_dates[1][0]

        # ── Load current and previous snapshots ───────────────────────────────
        current_rows = self.db.execute(text("""
            SELECT s.schemecode, s.fund_name, s.rank_in_category, s.sharpe_score,
                   sr.sharpe_ratio_3yr
            FROM selfmade_ranking_snapshot s
            LEFT JOIN selfmade_scheme_ranking sr
                   ON sr.schemecode = s.schemecode AND sr.category = s.category
            WHERE s.snapshot_date = :dt AND s.category = :cat
            ORDER BY s.rank_in_category
        """), {"dt": current_date, "cat": category_name}).fetchall()

        prev_rank_map: dict[int, int] = {}
        prev_rows = self.db.execute(text("""
            SELECT schemecode, rank_in_category
            FROM selfmade_ranking_snapshot
            WHERE snapshot_date = :dt AND category = :cat
        """), {"dt": prev_date, "cat": category_name}).fetchall()
        for pr in prev_rows:
            prev_rank_map[pr[0]] = pr[1]

        if not current_rows:
            return results

        # ── Compute improvers (rank_delta <= -3 AND current_rank <= 30) ───────
        improvers = []
        for r in current_rows:
            sc, name, curr_rank, sharpe_snap, sharpe_ranking = r
            prev_rank = prev_rank_map.get(sc)
            if prev_rank is None:
                continue
            rank_delta = curr_rank - prev_rank
            if rank_delta <= -3 and curr_rank <= 30:
                sharpe_val = float(sharpe_ranking or sharpe_snap or 0)
                improvers.append({
                    "schemecode": sc,
                    "fund_name": name,
                    "current_rank": curr_rank,
                    "prev_rank": prev_rank,
                    "rank_delta": rank_delta,
                    "sharpe": sharpe_val,
                })

        # Sort by most improved (most negative delta first)
        improvers.sort(key=lambda x: x["rank_delta"])

        # ── Emit count template ───────────────────────────────────────────────
        if improvers:
            best = improvers[0]
            results.append({
                "template_id": "AIW_RANK_IMPROVERS_COUNT_POSITIVE_V1",
                "variables": {
                    "count": len(improvers),
                    "category": category_name,
                    "top_improver_name": best["fund_name"],
                    "prev_rank": best["prev_rank"],
                    "current_rank": best["current_rank"],
                },
            })
            results.append({
                "template_id": "AIW_BIGGEST_RANK_IMPROVER_POSITIVE_V1",
                "variables": {
                    "fund_name": best["fund_name"],
                    "category": category_name,
                    "prev_rank": best["prev_rank"],
                    "current_rank": best["current_rank"],
                    "delta": abs(best["rank_delta"]),
                    "sharpe": best["sharpe"],
                },
            })
        else:
            results.append({
                "template_id": "AIW_RANK_IMPROVERS_COUNT_ZERO_V1",
                "variables": {"category": category_name},
            })
            results.append({
                "template_id": "AIW_BIGGEST_RANK_IMPROVER_NONE_V1",
                "variables": {"category": category_name},
            })

        return results

    def evaluate_workspace_daily_briefing(
        self, category_name: str, evaluation_date: date,
    ) -> list[dict]:
        """
        Workspace daily briefing — delegates to V1 logic.
        Returns V1 AIW_* insight cards based on ranking snapshots.
        """
        return self.generate_workspace_daily_briefing_insights(category_name, evaluation_date)

    def generate_category_ranking_insights(
        self, category_name: str, evaluation_date: date,
    ) -> list[dict]:
        """
        Category rankings page — uses CAT_*_V1 templates.
        Reads from selfmade_ranking_snapshot (6-month history).
        Improver definition: rank_delta ≤ -3 AND current_rank ≤ 30.
        Deterioration: rank_delta ≥ +3 AND prev_rank ≤ 20.
        """
        results: list[dict] = []

        # ── Fetch 2 most recent snapshots for this category ───────────────────
        dates = self.db.execute(text("""
            SELECT DISTINCT snapshot_date
            FROM selfmade_ranking_snapshot
            WHERE category = :cat
            ORDER BY snapshot_date DESC
            LIMIT 2
        """), {"cat": category_name}).fetchall()

        if len(dates) < 2:
            # Partial data guard
            results.append({
                "template_id": "CAT_TOP_STRUCTURAL_IMPROVER_PARTIAL_V1",
                "variables": {"category": category_name},
            })
            return results

        cur_date = dates[0][0]
        prev_date = dates[1][0]

        # Current snapshot with IR slope proxy
        cur_rows = self.db.execute(text("""
            SELECT
                s.schemecode,
                s.fund_name,
                s.rank_in_category,
                s.composite_score_v2,
                s.information_ratio_3yr,
                sm.ir_slope_6m_proxy
            FROM selfmade_ranking_snapshot s
            LEFT JOIN selfmade_scheme_metrics sm ON sm.schemecode = s.schemecode
            WHERE s.snapshot_date = :dt AND s.category = :cat
            ORDER BY s.rank_in_category
        """), {"dt": cur_date, "cat": category_name}).fetchall()

        prev_rank_map: dict[int, int] = {
            r[0]: r[1]
            for r in self.db.execute(text("""
                SELECT schemecode, rank_in_category
                FROM selfmade_ranking_snapshot
                WHERE snapshot_date = :dt AND category = :cat
            """), {"dt": prev_date, "cat": category_name}).fetchall()
        }

        if not cur_rows:
            return results

        total = len(cur_rows)

        # ── 1. Structural improvers ───────────────────────────────────────────
        improvers = []
        for r in cur_rows:
            sc, name, curr_rank, score, ir3, ir_slope = r
            prev = prev_rank_map.get(sc)
            if prev is None:
                continue
            delta = curr_rank - prev  # negative = improved
            if delta <= -3 and curr_rank <= 30:
                improvers.append({
                    "schemecode": sc,
                    "fund_name": name,
                    "current_rank": curr_rank,
                    "prev_rank": prev,
                    "delta": delta,
                    "score": float(score or 0),
                    "ir_slope": float(ir_slope or 0),
                })

        improvers.sort(key=lambda x: x["delta"])

        if improvers:
            best = improvers[0]
            results.append({
                "template_id": "CAT_TOP_STRUCTURAL_IMPROVER_FOUND_V1",
                "variables": {
                    "fund_name": best["fund_name"],
                    "category": category_name,
                    "abs_delta": abs(best["delta"]),
                    "prev_rank": best["prev_rank"],
                    "current_rank": best["current_rank"],
                    "composite_score": best["score"],
                    "ir_slope": best["ir_slope"],
                },
            })
        else:
            results.append({
                "template_id": "CAT_TOP_STRUCTURAL_IMPROVER_NONE_V1",
                "variables": {"category": category_name},
            })

        # ── 2. Deteriorating top-ranked funds ─────────────────────────────────
        deteriorating = []
        for r in cur_rows:
            sc, name, curr_rank, score, ir3, ir_slope = r
            prev = prev_rank_map.get(sc)
            if prev is None:
                continue
            delta = curr_rank - prev
            if delta >= 3 and prev <= 20:
                deteriorating.append({
                    "fund_name": name,
                    "current_rank": curr_rank,
                    "prev_rank": prev,
                    "delta": delta,
                    "score": float(score or 0),
                })

        deteriorating.sort(key=lambda x: x["delta"], reverse=True)

        if deteriorating:
            worst = deteriorating[0]
            results.append({
                "template_id": "CAT_TOP_RANKED_DETERIORATING_FOUND_V1",
                "variables": {
                    "fund_name": worst["fund_name"],
                    "category": category_name,
                    "abs_delta": worst["delta"],
                    "prev_rank": worst["prev_rank"],
                    "current_rank": worst["current_rank"],
                    "composite_score": worst["score"],
                },
            })
        else:
            results.append({
                "template_id": "CAT_TOP_RANKED_DETERIORATING_NONE_V1",
                "variables": {"category": category_name},
            })

        # ── 3. New top-30 entrants ────────────────────────────────────────────
        entrants = []
        for r in cur_rows:
            sc, name, curr_rank, score, ir3, ir_slope = r
            prev = prev_rank_map.get(sc)
            if curr_rank <= 30 and (prev is None or prev > 30):
                entrants.append({"fund_name": name, "prev_rank": prev or "—"})

        if entrants:
            results.append({
                "template_id": "CAT_NEW_TOP_30_ENTRANTS_POSITIVE_V1",
                "variables": {
                    "entrant_count": len(entrants),
                    "category": category_name,
                    "entrant_names": ", ".join(e["fund_name"] for e in entrants[:3]),
                    "prev_ranks": ", ".join(str(e["prev_rank"]) for e in entrants[:3]),
                },
            })
        else:
            results.append({
                "template_id": "CAT_NEW_TOP_30_ENTRANTS_ZERO_V1",
                "variables": {"category": category_name},
            })

        # ── 4. Tight score cluster ────────────────────────────────────────────
        if len(cur_rows) >= 10:
            r1 = cur_rows[0]
            r10 = cur_rows[9]
            score1 = float(r1[3] or 0)
            score10 = float(r10[3] or 0)
            gap = score1 - score10
            shared = {
                "category": category_name,
                "rank1_name": r1[1],
                "rank1_score": score1,
                "rank10_name": r10[1],
                "rank10_score": score10,
                "score_gap": round(gap, 2),
            }
            results.append({
                "template_id": (
                    "CAT_TIGHT_SCORE_CLUSTER_TRUE_V1"
                    if gap < SCORE_TIGHT_CLUSTER_THRESHOLD
                    else "CAT_TIGHT_SCORE_CLUSTER_FALSE_V1"
                ),
                "variables": shared,
            })

        # ── 5. Improvement breadth ────────────────────────────────────────────
        n_improving = sum(
            1 for r in cur_rows
            if prev_rank_map.get(r[0]) is not None
            and r[2] < prev_rank_map[r[0]]
        )
        n_deteriorating = sum(
            1 for r in cur_rows
            if prev_rank_map.get(r[0]) is not None
            and r[2] > prev_rank_map[r[0]]
        )
        n_with_prev = sum(1 for r in cur_rows if prev_rank_map.get(r[0]) is not None)

        if n_with_prev > 0:
            imp_pct = n_improving / n_with_prev * 100
            det_pct = n_deteriorating / n_with_prev * 100
            if imp_pct >= 55:
                results.append({
                    "template_id": "CAT_IMPROVEMENT_BREADTH_POSITIVE_V1",
                    "variables": {
                        "category": category_name,
                        "improving_count": n_improving,
                        "total_count": n_with_prev,
                        "improving_pct": round(imp_pct, 1),
                    },
                })
            elif det_pct >= 55:
                results.append({
                    "template_id": "CAT_IMPROVEMENT_BREADTH_NEGATIVE_V1",
                    "variables": {
                        "category": category_name,
                        "deteriorating_count": n_deteriorating,
                        "total_count": n_with_prev,
                        "deteriorating_pct": round(det_pct, 1),
                    },
                })
            else:
                results.append({
                    "template_id": "CAT_IMPROVEMENT_BREADTH_BALANCED_V1",
                    "variables": {
                        "category": category_name,
                        "improving_count": n_improving,
                        "deteriorating_count": n_deteriorating,
                        "total_count": n_with_prev,
                    },
                })

        return results

    def evaluate_category_ranking_insights(
        self, category_name: str, evaluation_date: date,
    ) -> list[dict]:
        """Category rankings page — delegates to V1 logic."""
        return self.generate_category_ranking_insights(category_name, evaluation_date)

    def generate_fund_detail_insights(
        self, schemecode: int, evaluation_date: date,
    ) -> list[dict]:
        """Fund detail page — 21 FUND_*_V1 templates across 5 groups."""
        results: list[dict] = []

        # ── Group 1: Holdings availability ────────────────────────────────────
        holding_row = self.db.execute(text("""
            SELECT COUNT(*) AS cnt,
                   SUM(holding_weight_pct) AS total_wt,
                   MAX(as_of_date) AS latest_date
            FROM selfmade_portfolio_holding
            WHERE scheme_id = :sc
        """), {"sc": schemecode}).fetchone()

        holding_count = int(holding_row[0]) if holding_row else 0
        weight_coverage = float(holding_row[1] or 0) if holding_row else 0.0
        holdings_date = holding_row[2] if holding_row else None

        if holding_count == 0:
            results.append({
                "template_id": "FUND_HOLDINGS_AVAIL_NONE_V1",
                "variables": {},
            })
        else:
            from datetime import timedelta
            days_stale = (evaluation_date - holdings_date).days if holdings_date else 999
            if days_stale <= 30:
                results.append({
                    "template_id": "FUND_HOLDINGS_DATA_FRESH_V1",
                    "variables": {"as_of_date": str(holdings_date)},
                })
            elif days_stale > 60:
                results.append({
                    "template_id": "FUND_HOLDINGS_AVAIL_STALE_V1",
                    "variables": {"as_of_date": str(holdings_date)},
                })
            else:
                results.append({
                    "template_id": "FUND_HOLDINGS_AVAIL_FULL_V1",
                    "variables": {
                        "holding_count": holding_count,
                        "as_of_date": str(holdings_date),
                        "weight_coverage": weight_coverage,
                    },
                })

        # ── Group 2: Concentration ─────────────────────────────────────────────
        if holding_count > 0:
            top_holdings = self.db.execute(text("""
                SELECT sm.company_name, ph.holding_weight_pct
                FROM selfmade_portfolio_holding ph
                JOIN selfmade_security_master sm ON sm.id = ph.security_id
                WHERE ph.scheme_id = :sc
                  AND ph.as_of_date = :dt
                ORDER BY ph.holding_weight_pct DESC
                LIMIT 5
            """), {"sc": schemecode, "dt": holdings_date}).fetchall()

            if top_holdings:
                top5_pct = sum(float(r[1] or 0) for r in top_holdings)
                top3_names = ", ".join(r[0] for r in top_holdings[:3])
                top1_name = top_holdings[0][0]
                top1_pct = float(top_holdings[0][1] or 0)
                top3_pct = sum(float(r[1] or 0) for r in top_holdings[:3])

                if top5_pct >= TOP_5_CONCENTRATION_HIGH:
                    results.append({
                        "template_id": "FUND_CONC_HIGH_V1",
                        "variables": {
                            "top5_pct": top5_pct,
                            "threshold": TOP_5_CONCENTRATION_HIGH,
                            "top3_names": top3_names,
                        },
                    })
                elif top5_pct >= TOP_5_CONCENTRATION_MODERATE:
                    results.append({
                        "template_id": "FUND_CONC_MODERATE_V1",
                        "variables": {
                            "top5_pct": top5_pct,
                            "lower": TOP_5_CONCENTRATION_MODERATE,
                            "upper": TOP_5_CONCENTRATION_HIGH,
                            "top3_names": top3_names,
                        },
                    })
                else:
                    results.append({
                        "template_id": "FUND_CONC_LOW_V1",
                        "variables": {
                            "top5_pct": top5_pct,
                            "top3_names": top3_names,
                        },
                    })

                results.append({
                    "template_id": "FUND_CONC_TOP_NAMES_V1",
                    "variables": {
                        "top1_name": top1_name,
                        "top1_pct": top1_pct,
                        "top3_names": top3_names,
                        "top3_pct": top3_pct,
                    },
                })

        # ── Group 3: Sectors ───────────────────────────────────────────────────
        if holding_count > 0:
            sector_rows = self.db.execute(text("""
                SELECT sm.sector, SUM(ph.holding_weight_pct) AS sector_wt
                FROM selfmade_portfolio_holding ph
                JOIN selfmade_security_master sm ON sm.id = ph.security_id
                WHERE ph.scheme_id = :sc AND ph.as_of_date = :dt
                  AND sm.sector IS NOT NULL
                GROUP BY sm.sector
                ORDER BY sector_wt DESC
            """), {"sc": schemecode, "dt": holdings_date}).fetchall()

            if sector_rows:
                total_sector_wt = sum(float(r[1] or 0) for r in sector_rows)
                sectors_to_80: int = 0
                cumulative = 0.0
                for r in sector_rows:
                    cumulative += float(r[1] or 0)
                    sectors_to_80 += 1
                    if total_sector_wt > 0 and cumulative / total_sector_wt >= 0.80:
                        break

                top_sector_name = sector_rows[0][0]
                max_sector_pct = float(sector_rows[0][1] or 0)
                top3_sectors = ", ".join(r[0] for r in sector_rows[:3])

                if sectors_to_80 <= SECTORS_TO_80_CONCENTRATED:
                    results.append({
                        "template_id": "FUND_SECTOR_CONCENTRATED_V1",
                        "variables": {
                            "sectors_to_80": sectors_to_80,
                            "top_sectors": top3_sectors,
                        },
                    })
                elif sectors_to_80 >= SECTORS_TO_80_MODERATE:
                    results.append({
                        "template_id": "FUND_SECTOR_DIVERSIFIED_V1",
                        "variables": {
                            "sectors_to_80": sectors_to_80,
                            "top_sectors": top3_sectors,
                        },
                    })

                fin_wt = sum(
                    float(r[1] or 0) for r in sector_rows
                    if (r[0] or "").lower() in {"financials", "financial services"}
                )
                if fin_wt > 35.0:
                    results.append({
                        "template_id": "FUND_SECTOR_FIN_HEAVY_V1",
                        "variables": {
                            "fin_pct": fin_wt,
                            "threshold": 35,
                        },
                    })
                elif max_sector_pct <= 25.0:
                    results.append({
                        "template_id": "FUND_SECTOR_BALANCED_V1",
                        "variables": {
                            "max_sector_pct": max_sector_pct,
                            "top_sector_name": top_sector_name,
                        },
                    })

        # ── Group 4: 3Y Performance ────────────────────────────────────────────
        metrics_row = self.db.execute(text("""
            SELECT information_ratio_3yr, sharpe_ratio_3yr
            FROM selfmade_scheme_metrics
            WHERE schemecode = :sc
        """), {"sc": schemecode}).fetchone()

        returns_row = self.db.execute(text("""
            SELECT fund_3yr_ret, active_3yr_ret, benchmark_index
            FROM selfmade_scheme_returns
            WHERE schemecode = :sc
        """), {"sc": schemecode}).fetchone()

        snap_row = self.db.execute(text("""
            SELECT s.rank_in_category, sr.total_in_category, s.category,
                   s.composite_score_v2, sr.pct_ir_3yr, sr.pct_sharpe_3yr,
                   s.rank_delta_6m
            FROM selfmade_ranking_snapshot s
            LEFT JOIN selfmade_scheme_ranking sr ON sr.schemecode = s.schemecode
            WHERE s.schemecode = :sc
            ORDER BY s.snapshot_date DESC LIMIT 1
        """), {"sc": schemecode}).fetchone()

        snap_prev = self.db.execute(text("""
            SELECT rank_in_category FROM selfmade_ranking_snapshot
            WHERE schemecode = :sc
            ORDER BY snapshot_date DESC
            LIMIT 1 OFFSET 1
        """), {"sc": schemecode}).fetchone()

        if metrics_row:
            ir3 = float(metrics_row[0]) if metrics_row[0] is not None else None

            if ir3 is not None:
                if ir3 > 0.5:
                    rank_ic = int(snap_row[0]) if snap_row else 0
                    total_ic = int(snap_row[1]) if snap_row else 0
                    results.append({
                        "template_id": "FUND_PERF_IR_STRONG_V1",
                        "variables": {
                            "ir_3yr": ir3,
                            "threshold": 0.5,
                            "rank_in_category": rank_ic,
                            "total_in_category": total_ic,
                        },
                    })
                elif ir3 < 0.1:
                    rank_ic = int(snap_row[0]) if snap_row else 0
                    total_ic = int(snap_row[1]) if snap_row else 0
                    results.append({
                        "template_id": "FUND_PERF_IR_WEAK_V1",
                        "variables": {
                            "ir_3yr": ir3,
                            "threshold": 0.1,
                            "rank_in_category": rank_ic,
                            "total_in_category": total_ic,
                        },
                    })

        if returns_row:
            fund_3yr = float(returns_row[0]) if returns_row[0] is not None else None
            active_3yr = float(returns_row[1]) if returns_row[1] is not None else None
            bm_name = returns_row[2] or "benchmark"

            if active_3yr is not None and fund_3yr is not None:
                if active_3yr > 2.0:
                    results.append({
                        "template_id": "FUND_PERF_ALPHA_POSITIVE_V1",
                        "variables": {
                            "active_3yr_ret": active_3yr,
                            "benchmark_name": bm_name,
                            "threshold": 2.0,
                            "fund_3yr_ret": fund_3yr,
                        },
                    })
                elif active_3yr < 0.0:
                    results.append({
                        "template_id": "FUND_PERF_ALPHA_NEGATIVE_V1",
                        "variables": {
                            "active_3yr_ret": active_3yr,
                            "benchmark_name": bm_name,
                            "fund_3yr_ret": fund_3yr,
                        },
                    })

        if snap_row:
            rank = int(snap_row[0])
            total = int(snap_row[1])
            cat = snap_row[2]
            score = float(snap_row[3] or 0)
            pct_ir = float(snap_row[4] or 50)
            pct_sharpe = float(snap_row[5] or 50)

            if score >= 85:
                tier = "Strong"
            elif score >= 50:
                tier = "Good"
            elif score >= 15:
                tier = "Neutral"
            else:
                tier = "Weak"

            results.append({
                "template_id": "FUND_PERF_RANK_TIER_V1",
                "variables": {
                    "rank_in_category": rank,
                    "total_in_category": total,
                    "category": cat,
                    "tier": tier,
                    "composite_score": score,
                    "pct_ir": pct_ir,
                    "pct_sharpe": pct_sharpe,
                },
            })

        # ── Group 5: Trend ─────────────────────────────────────────────────────
        if snap_row:
            rank = int(snap_row[0])
            total = int(snap_row[1])
            cat = snap_row[2]
            score = float(snap_row[3] or 0)
            rank_delta = snap_row[6]

            prev_rank = int(snap_prev[0]) if snap_prev else None

            if prev_rank is None:
                results.append({
                    "template_id": "FUND_TREND_NEW_V1",
                    "variables": {
                        "category": cat,
                        "current_rank": rank,
                        "total_in_category": total,
                    },
                })
            elif rank_delta is not None and int(rank_delta) <= -RANK_IMPROVEMENT_THRESHOLD:
                results.append({
                    "template_id": "FUND_TREND_IMPROVING_V1",
                    "variables": {
                        "abs_delta": abs(int(rank_delta)),
                        "prev_rank": prev_rank,
                        "current_rank": rank,
                        "category": cat,
                        "composite_score": score,
                    },
                })
            elif rank_delta is not None and int(rank_delta) >= RANK_IMPROVEMENT_THRESHOLD:
                results.append({
                    "template_id": "FUND_TREND_DECLINING_V1",
                    "variables": {
                        "abs_delta": int(rank_delta),
                        "prev_rank": prev_rank,
                        "current_rank": rank,
                        "category": cat,
                        "composite_score": score,
                    },
                })
            else:
                results.append({
                    "template_id": "FUND_TREND_STABLE_V1",
                    "variables": {
                        "current_rank": rank,
                        "category": cat,
                        "rank_delta": int(rank_delta) if rank_delta is not None else 0,
                        "composite_score": score,
                    },
                })

        return results

    def evaluate_fund_detail_insights(
        self, schemecode: int, evaluation_date: date,
    ) -> list[dict]:
        """Fund detail page — delegates to V1 logic."""
        return self.generate_fund_detail_insights(schemecode, evaluation_date)

    def evaluate_fund_comparison_insights(
        self, schemecodes: list[int], evaluation_date: date,
    ) -> list[dict]:
        """
        Fund comparison page — 28 CMP_*_V1 templates.

        Fires exactly one template per slot:
          holdings_overlap | sector_overlap | category | ir | improvement | laggard | best_overall
        Each template fires AT MOST ONCE (deduplicated by template_id).
        """
        results: list[dict] = []
        fired: set[str] = set()

        def _add(template_id: str, variables: dict) -> None:
            if template_id not in fired:
                fired.add(template_id)
                results.append({"template_id": template_id, "variables": variables})

        # ── Load per-fund ranking + metrics data ──────────────────────────────
        fund_data: list[dict] = []
        for sc in schemecodes:
            row = self.db.execute(text("""
                SELECT sr.schemecode, sr.amfi_name, sr.category,
                       sr.rank_in_category, sr.rank_delta, sr.composite_score,
                       sm.information_ratio_3yr, sm.ir_slope_6m_proxy
                FROM selfmade_scheme_ranking sr
                JOIN selfmade_scheme_metrics sm USING (schemecode)
                WHERE sr.schemecode = :sc
            """), {"sc": sc}).fetchone()
            if row:
                fund_data.append({
                    "sc": row[0],
                    "name": row[1],
                    "category": row[2],
                    "rank": int(row[3]) if row[3] is not None else None,
                    "rank_delta": int(row[4]) if row[4] is not None else None,
                    "score": float(row[5]) if row[5] is not None else 0.0,
                    "ir": float(row[6]) if row[6] is not None else None,
                    "ir_slope": float(row[7]) if row[7] is not None else None,
                })

        if not fund_data:
            return results

        is_two_fund = len(schemecodes) == 2
        fund_names_str = ", ".join(f["name"] for f in fund_data)

        # ── 1. Holdings overlap ───────────────────────────────────────────────
        overlap = get_overlap_metrics(self.db, schemecodes)
        wo = overlap["weighted_overlap"]
        has_overlap_data = wo > 0 or overlap["common_count"] > 0

        if is_two_fund:
            fa_name = fund_data[0]["name"] if len(fund_data) > 0 else "Fund A"
            fb_name = fund_data[1]["name"] if len(fund_data) > 1 else "Fund B"
            common_count = overlap["common_count"]
            jaccard = overlap["jaccard"]

            if not has_overlap_data:
                _add("CMP_HOLDINGS_OVERLAP_UNAVAILABLE_2F_V1", {})
            elif wo >= HOLDINGS_OVERLAP_VERY_HIGH:
                _add("CMP_HOLDINGS_OVERLAP_VERY_HIGH_2F_V1", {
                    "fund_a_name": fa_name, "fund_b_name": fb_name,
                    "weighted_overlap": wo, "common_count": common_count, "jaccard": jaccard,
                })
            elif wo >= HOLDINGS_OVERLAP_HIGH:
                _add("CMP_HOLDINGS_OVERLAP_HIGH_2F_V1", {
                    "fund_a_name": fa_name, "fund_b_name": fb_name,
                    "weighted_overlap": wo, "common_count": common_count, "jaccard": jaccard,
                })
            elif wo >= HOLDINGS_OVERLAP_MODERATE:
                _add("CMP_HOLDINGS_OVERLAP_MODERATE_2F_V1", {
                    "fund_a_name": fa_name, "fund_b_name": fb_name,
                    "weighted_overlap": wo, "common_count": common_count, "jaccard": jaccard,
                })
            else:
                _add("CMP_HOLDINGS_OVERLAP_LOW_2F_V1", {
                    "fund_a_name": fa_name, "fund_b_name": fb_name,
                    "weighted_overlap": wo, "common_count": common_count, "jaccard": jaccard,
                })
        else:
            num_funds = len(fund_data)
            if not has_overlap_data:
                _add("CMP_HOLDINGS_OVERLAP_MULTI_UNAVAILABLE_V1", {
                    "num_funds": num_funds, "fund_names": fund_names_str,
                })
            elif wo >= HOLDINGS_OVERLAP_HIGH:
                _add("CMP_HOLDINGS_OVERLAP_MULTI_HIGH_V1", {
                    "num_funds": num_funds, "fund_names": fund_names_str,
                    "avg_pairwise_overlap": wo,
                })
            elif wo >= HOLDINGS_OVERLAP_MODERATE:
                _add("CMP_HOLDINGS_OVERLAP_MULTI_MODERATE_V1", {
                    "num_funds": num_funds, "fund_names": fund_names_str,
                    "avg_pairwise_overlap": wo,
                })
            else:
                _add("CMP_HOLDINGS_OVERLAP_MULTI_LOW_V1", {
                    "num_funds": num_funds, "fund_names": fund_names_str,
                    "avg_pairwise_overlap": wo,
                })

        # ── 2. Sector overlap ─────────────────────────────────────────────────
        so = overlap["sector_overlap"]
        has_sector_data = overlap["common_sectors"] > 0 or so > 0

        if not has_sector_data:
            _add("CMP_SECTOR_OVERLAP_UNAVAILABLE_V1", {"fund_names": fund_names_str})
        elif so >= 70:
            _add("CMP_SECTOR_OVERLAP_HIGH_V1", {"fund_names": fund_names_str, "sector_overlap": so})
        elif so >= 40:
            _add("CMP_SECTOR_OVERLAP_MODERATE_V1", {"fund_names": fund_names_str, "sector_overlap": so})
        else:
            _add("CMP_SECTOR_OVERLAP_LOW_V1", {"fund_names": fund_names_str, "sector_overlap": so})

        # ── 3. Category ───────────────────────────────────────────────────────
        categories = {f["category"] for f in fund_data if f["category"]}
        scores = [f["score"] for f in fund_data]
        score_gap = round(max(scores) - min(scores), 2) if scores else 0.0

        if len(categories) == 1:
            cat = next(iter(categories))
            leader = max(fund_data, key=lambda f: f["score"])
            # Count how many metrics the leader wins vs the second-best
            others = [f for f in fund_data if f["sc"] != leader["sc"]]
            metrics_won = 0
            for other in others:
                if leader["ir"] is not None and other["ir"] is not None and leader["ir"] > other["ir"]:
                    metrics_won += 1
                if leader["rank"] is not None and other["rank"] is not None and leader["rank"] < other["rank"]:
                    metrics_won += 1
            if score_gap >= 5 and metrics_won >= 2:
                _add("CMP_SAME_CATEGORY_CLEAR_LEADER_V1", {
                    "leader_name": leader["name"], "category": cat,
                    "score_gap": score_gap, "metrics_won": metrics_won,
                })
            else:
                _add("CMP_SAME_CATEGORY_NO_CLEAR_LEADER_V1", {
                    "category": cat, "score_gap": score_gap,
                })
        else:
            cats_str = ", ".join(sorted(categories))
            _add("CMP_DIFFERENT_CATEGORY_NO_LEADER_V1", {
                "categories_str": cats_str, "num_categories": len(categories),
            })

        # ── 4. IR leadership ──────────────────────────────────────────────────
        funds_with_ir = [f for f in fund_data if f["ir"] is not None]
        if not funds_with_ir:
            _add("CMP_IR_UNAVAILABLE_V1", {"fund_names": fund_names_str})
        else:
            funds_sorted_ir = sorted(funds_with_ir, key=lambda f: f["ir"], reverse=True)
            ir_leader = funds_sorted_ir[0]
            gap = (ir_leader["ir"] - funds_sorted_ir[1]["ir"]) if len(funds_sorted_ir) >= 2 else 0.0

            # Check for IR conflict: leader on IR != leader on slope
            funds_with_slope = [f for f in fund_data if f["ir_slope"] is not None]
            ir_conflict = False
            slope_leader = None
            if funds_with_slope and len(funds_with_ir) >= 2:
                slope_leader_f = max(funds_with_slope, key=lambda f: f["ir_slope"])
                if slope_leader_f["sc"] != ir_leader["sc"] and slope_leader_f["ir_slope"] > IR_SLOPE_IMPROVING:
                    ir_conflict = True
                    slope_leader = slope_leader_f

            if ir_conflict and slope_leader is not None:
                _add("CMP_IR_CONFLICT_RECENT_IMPROVER_V1", {
                    "ir_leader_name": ir_leader["name"],
                    "slope_leader_name": slope_leader["name"],
                    "ir_leader_val": ir_leader["ir"],
                    "slope_leader_val": slope_leader["ir_slope"],
                })
            elif gap > IR_GAP_CLEAR_THRESHOLD:
                _add("CMP_IR_LEADER_CLEAR_V1", {
                    "leader_name": ir_leader["name"], "leader_ir": ir_leader["ir"], "gap": gap,
                })
            else:
                _add("CMP_IR_LEADER_CLOSE_V1", {
                    "leader_name": ir_leader["name"], "leader_ir": ir_leader["ir"], "gap": gap,
                })

        # ── 5. Recent improvement ─────────────────────────────────────────────
        # Use ir_slope as improvement signal
        funds_with_slope = [f for f in fund_data if f["ir_slope"] is not None]
        if not funds_with_slope:
            _add("CMP_RECENT_IMPROVEMENT_NONE_V1", {"fund_names": fund_names_str})
        else:
            slopes_sorted = sorted(funds_with_slope, key=lambda f: f["ir_slope"], reverse=True)
            top = slopes_sorted[0]
            gap_imp = (top["ir_slope"] - slopes_sorted[1]["ir_slope"]) if len(slopes_sorted) >= 2 else 0.0

            if top["ir_slope"] <= 0:
                _add("CMP_RECENT_IMPROVEMENT_NONE_V1", {"fund_names": fund_names_str})
            elif gap_imp >= 0.01:
                _add("CMP_RECENT_IMPROVEMENT_LEADER_CLEAR_V1", {
                    "leader_name": top["name"],
                    "improvement_score": top["ir_slope"],
                    "gap": gap_imp,
                })
            else:
                _add("CMP_RECENT_IMPROVEMENT_CLOSE_V1", {
                    "leader_name": top["name"],
                    "improvement_score": top["ir_slope"],
                    "gap": gap_imp,
                })

        # ── 6. Laggard ────────────────────────────────────────────────────────
        if len(fund_data) >= 2:
            laggard = min(fund_data, key=lambda f: f["score"])
            weak_conditions: list[str] = []
            clear_laggard = False

            # Clear laggard: IR < 0, slope < IR_SLOPE_WEAKENING, rank worsened
            if laggard["ir"] is not None and laggard["ir"] < 0:
                weak_conditions.append(f"IR {laggard['ir']:.2f}")
            if laggard["ir_slope"] is not None and laggard["ir_slope"] < IR_SLOPE_WEAKENING:
                weak_conditions.append(f"IR slope {laggard['ir_slope']:+.4f}/month")
            if laggard["rank_delta"] is not None and laggard["rank_delta"] >= RANK_IMPROVEMENT_THRESHOLD:
                weak_conditions.append(f"rank dropped {laggard['rank_delta']} places")

            if len(weak_conditions) >= 2:
                clear_laggard = True

            if clear_laggard:
                _add("CMP_LAGGARD_CLEAR_V1", {
                    "laggard_name": laggard["name"],
                    "laggard_ir_pct": laggard["ir"] if laggard["ir"] is not None else 0.0,
                    "laggard_ir_slope": laggard["ir_slope"] if laggard["ir_slope"] is not None else 0.0,
                    "laggard_downside_capture": "N/A",
                    "rank_delta": laggard["rank_delta"] if laggard["rank_delta"] is not None else 0,
                })
            elif weak_conditions:
                _add("CMP_LAGGARD_SOFT_V1", {
                    "laggard_name": laggard["name"],
                    "weak_conditions": ", ".join(weak_conditions),
                })
            else:
                _add("CMP_LAGGARD_NONE_V1", {"fund_names": fund_names_str})

        # ── 7. Best overall ───────────────────────────────────────────────────
        winner = max(fund_data, key=lambda f: f["score"])
        others = [f for f in fund_data if f["sc"] != winner["sc"]]
        score_gap_best = round(winner["score"] - min(f["score"] for f in fund_data), 2) if others else 0.0

        metrics_won_count = 0
        for other in others:
            if winner["ir"] is not None and other["ir"] is not None and winner["ir"] > other["ir"]:
                metrics_won_count += 1
            if winner["rank"] is not None and other["rank"] is not None and winner["rank"] < other["rank"]:
                metrics_won_count += 1
            if winner["ir_slope"] is not None and other["ir_slope"] is not None and winner["ir_slope"] > other["ir_slope"]:
                metrics_won_count += 1

        winner_cat = winner["category"] or (next(iter(categories)) if categories else "")

        if score_gap_best >= 5 and metrics_won_count >= 2:
            _add("CMP_BEST_CLEAR_V1", {
                "winner_name": winner["name"],
                "category": winner_cat,
                "score_gap": score_gap_best,
                "metrics_won_count": metrics_won_count,
            })
        else:
            reason = (
                "score gap is narrow" if score_gap_best < 5
                else "no single fund dominates across IR, rank, and improvement"
            )
            _add("CMP_BEST_NO_CLEAR_WINNER_V1", {
                "fund_names": fund_names_str,
                "reason": reason,
            })

        return results

    def evaluate_rule_playground_insights(
        self,
        sandbox_weights: dict,
        sandbox_results: list,
        current_top10: list,
    ) -> list[dict]:
        """Rule playground insight cards — computed live, no DB needed."""
        results: list[dict] = []

        # Weight validation
        total_weight = sum(sandbox_weights.values())
        if abs(total_weight - 100) < 0.01:
            status = "Valid"
            msg = "Weights sum to 100%"
            severity_override = "positive"
        else:
            status = "Invalid"
            msg = f"Weights sum to {total_weight:.0f}% — must equal 100%"
            severity_override = "negative"

        results.append({
            "template_id": "RULE_WEIGHT_VALIDATION",
            "variables": {
                "validation_status": status,
                "total_weight": total_weight,
                "validation_message": msg,
            },
            "severity_override": severity_override,
        })

        # Recency bias
        short_keys = {"pct_1yr_ret", "1yr_ret", "1yr", "ret_1yr"}
        short_pct = sum(
            v for k, v in sandbox_weights.items()
            if k.lower() in short_keys
        )
        if short_pct > SHORT_WINDOW_WEIGHT_THRESHOLD:
            results.append({
                "template_id": "RULE_RECENCY_BIAS",
                "variables": {"short_pct": short_pct},
            })

        # Return-heavy
        return_keys = {"pct_1yr_ret", "pct_3yr_ret", "pct_5yr_ret",
                       "1yr_ret", "3yr_ret", "5yr_ret",
                       "ret_1yr", "ret_3yr", "ret_5yr"}
        risk_keys = {"pct_ir_3yr", "pct_sharpe_3yr", "ir_3yr", "sharpe_3yr"}
        return_pct = sum(v for k, v in sandbox_weights.items() if k.lower() in return_keys)
        risk_adj_pct = sum(v for k, v in sandbox_weights.items() if k.lower() in risk_keys)
        if return_pct > RETURN_HEAVY_THRESHOLD:
            results.append({
                "template_id": "RULE_RETURN_HEAVY",
                "variables": {
                    "return_pct": return_pct,
                    "risk_adj_pct": risk_adj_pct,
                },
            })

        # Churn warning
        if sandbox_results and current_top10:
            sandbox_top10_ids = set()
            for r in sandbox_results[:10]:
                sid = r.get("schemecode") or r.get("scheme_plan_id")
                if sid:
                    sandbox_top10_ids.add(str(sid))

            current_ids = set()
            for r in current_top10:
                sid = r.get("schemecode") or r.get("scheme_plan_id")
                if sid:
                    current_ids.add(str(sid))

            if current_ids:
                new_entrants = sandbox_top10_ids - current_ids
                dropped = current_ids - sandbox_top10_ids
                churn_pct = len(new_entrants) / max(len(current_ids), 1) * 100

                if churn_pct >= CHURN_WARNING_THRESHOLD:
                    results.append({
                        "template_id": "RULE_CHURN_WARNING",
                        "variables": {
                            "churn_pct": churn_pct,
                            "new_entrants": len(new_entrants),
                            "dropped": len(dropped),
                        },
                    })

        # Category bias
        if sandbox_results:
            cats = [r.get("category", "") for r in sandbox_results[:10]]
            if cats:
                from collections import Counter
                cat_counts = Counter(cats)
                dominant = cat_counts.most_common(1)[0]
                dominant_pct = dominant[1] / len(cats) * 100
                if dominant_pct >= 50:
                    results.append({
                        "template_id": "RULE_CATEGORY_BIAS",
                        "variables": {
                            "dominant_category": dominant[0],
                            "dominant_pct": dominant_pct,
                        },
                    })

        # Score leader gap
        if len(sandbox_results) >= 2:
            r1 = sandbox_results[0]
            r2 = sandbox_results[1]
            s1 = r1.get("composite_score", r1.get("score", 0))
            s2 = r2.get("composite_score", r2.get("score", 0))
            gap = s1 - s2
            if gap >= SCORE_LEADER_GAP_THRESHOLD:
                gap_comment = "Clear leader — large gap to the next fund"
            else:
                gap_comment = "Close competition — small changes could swap the top positions"
            results.append({
                "template_id": "RULE_SCORE_LEADER_GAP",
                "variables": {
                    "rank1_name": r1.get("fund_name", r1.get("amfi_name", "Rank 1")),
                    "rank1_score": s1,
                    "rank2_name": r2.get("fund_name", r2.get("amfi_name", "Rank 2")),
                    "rank2_score": s2,
                    "gap": gap,
                    "gap_commentary": gap_comment,
                },
            })

        # Approval readiness
        issues = []
        if abs(total_weight - 100) >= 0.01:
            issues.append("weights don't sum to 100%")
        if short_pct > SHORT_WINDOW_WEIGHT_THRESHOLD:
            issues.append("recency bias detected")
        if return_pct > RETURN_HEAVY_THRESHOLD:
            issues.append("return-heavy weighting")

        if not issues:
            readiness = "Ready"
            detail = "No issues detected with the current weight configuration"
            action = "This ruleset can be submitted for approval"
        else:
            readiness = "Review needed"
            detail = f"Issues: {', '.join(issues)}"
            action = "Address the flagged issues before submitting for approval"

        results.append({
            "template_id": "RULE_APPROVAL_READINESS",
            "variables": {
                "readiness_label": readiness,
                "readiness_detail": detail,
                "action_suggestion": action,
            },
            "severity_override": "positive" if not issues else "warning",
        })

        return results
