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
                "variables": {"category": category_name, "entity_id": category_name,
                              "evaluation_date": str(evaluation_date)},
            })
            results.append({
                "template_id": "AIW_BIGGEST_RANK_IMPROVER_SNAPSHOT_MISSING_V1",
                "variables": {"category": category_name, "entity_id": category_name,
                              "evaluation_date": str(evaluation_date)},
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
        eval_date_str = str(evaluation_date)
        if improvers:
            best = improvers[0]
            results.append({
                "template_id": "AIW_RANK_IMPROVERS_COUNT_V1",
                "variables": {
                    "count": len(improvers),
                    "category": category_name,
                    "entity_id": category_name,
                    "evaluation_date": eval_date_str,
                },
            })
            results.append({
                "template_id": "AIW_BIGGEST_RANK_IMPROVER_V1",
                "variables": {
                    "fund_name": best["fund_name"],
                    "category": category_name,
                    "entity_id": best["schemecode"],
                    "evaluation_date": eval_date_str,
                    "previous_rank": best["prev_rank"],
                    "current_rank": best["current_rank"],
                    "rank_improvement_abs": abs(best["rank_delta"]),
                },
            })
        else:
            results.append({
                "template_id": "AIW_NO_MEANINGFUL_IMPROVERS_V1",
                "variables": {"category": category_name, "entity_id": category_name,
                              "evaluation_date": eval_date_str},
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
            # Partial data guard — CAT_TOP_STRUCTURAL_IMPROVER_PARTIAL_V1 is not
            # in the new template set; fall back to the "no clear improver" card
            # rather than showing nothing.
            results.append({
                "template_id": "CAT_NO_CLEAR_IMPROVER_V1",
                "variables": {"category": category_name, "entity_id": category_name,
                              "evaluation_date": str(evaluation_date)},
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
        eval_date_str = str(evaluation_date)

        # ── 1. Top structural improver ─────────────────────────────────────────
        # New trigger (spec Section 2): rank_delta_6m <= -5 (not -3) AND
        # current_rank <= 30 AND ir_slope_3y > 0. Best rank_delta_6m wins.
        improvers = []
        for r in cur_rows:
            sc, name, curr_rank, score, ir3, ir_slope = r
            prev = prev_rank_map.get(sc)
            if prev is None:
                continue
            delta = curr_rank - prev  # negative = improved
            slope = float(ir_slope) if ir_slope is not None else None
            if delta <= -5 and curr_rank <= 30 and slope is not None and slope > 0:
                improvers.append({
                    "schemecode": sc, "fund_name": name, "current_rank": curr_rank,
                    "prev_rank": prev, "delta": delta, "score": float(score or 0),
                    "ir_slope": slope,
                })
        improvers.sort(key=lambda x: x["delta"])

        if improvers:
            best = improvers[0]
            outperf_rows = self.db.execute(text("""
                SELECT informationratio FROM ratio_3year_monthlyret
                WHERE schemecode = :sc AND informationratio IS NOT NULL
                ORDER BY ratiodate DESC LIMIT 12
            """), {"sc": best["schemecode"]}).fetchall()
            outperf_vals = [float(r[0]) for r in outperf_rows]
            outperf_pct = (
                round(sum(1 for v in outperf_vals if v > 0) / len(outperf_vals) * 100, 1)
                if outperf_vals else 50.0
            )
            results.append({
                "template_id": "CAT_TOP_STRUCTURAL_IMPROVER_V1",
                "variables": {
                    "fund_name": best["fund_name"], "category": category_name,
                    "entity_id": best["schemecode"], "evaluation_date": eval_date_str,
                    "rank_improvement_abs": abs(best["delta"]),
                    "current_rank": best["current_rank"],
                    "ir_slope_3y": round(best["ir_slope"], 4),
                    "outperformance_ratio_3y_pct": outperf_pct,
                },
            })
        else:
            results.append({
                "template_id": "CAT_NO_CLEAR_IMPROVER_V1",
                "variables": {"category": category_name, "entity_id": category_name,
                              "evaluation_date": eval_date_str},
            })

        # ── 2. Top-ranked weakening ─────────────────────────────────────────────
        # New trigger: current_rank <= 10 AND rank_delta_6m >= +3 AND ir_slope_3y < 0.
        weakening = []
        for r in cur_rows:
            sc, name, curr_rank, score, ir3, ir_slope = r
            prev = prev_rank_map.get(sc)
            if prev is None:
                continue
            delta = curr_rank - prev
            slope = float(ir_slope) if ir_slope is not None else None
            if curr_rank <= 10 and delta >= 3 and slope is not None and slope < 0:
                weakening.append({
                    "fund_name": name, "current_rank": curr_rank, "prev_rank": prev,
                    "delta": delta, "ir_slope": slope,
                })
        weakening.sort(key=lambda x: x["delta"], reverse=True)

        if weakening:
            worst = weakening[0]
            results.append({
                "template_id": "CAT_TOP_RANKED_WEAKENING_V1",
                "variables": {
                    "fund_name": worst["fund_name"], "category": category_name,
                    "entity_id": worst["fund_name"], "evaluation_date": eval_date_str,
                    "current_rank": worst["current_rank"],
                    "rank_decline_abs": worst["delta"],
                    "ir_slope_3y": round(worst["ir_slope"], 4),
                },
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
                "template_id": "CAT_NEW_TOP_30_ENTRANTS_V1",
                "variables": {
                    "count": len(entrants), "category": category_name,
                    "entity_id": category_name, "evaluation_date": eval_date_str,
                },
            })

        # ── 4. Tight score cluster ────────────────────────────────────────────
        if len(cur_rows) >= 10:
            score1 = float(cur_rows[0][3] or 0)
            score10 = float(cur_rows[9][3] or 0)
            gap = round(score1 - score10, 2)
            if gap < SCORE_TIGHT_CLUSTER_THRESHOLD:
                results.append({
                    "template_id": "CAT_TIGHT_SCORE_CLUSTER_V1",
                    "variables": {
                        "category": category_name, "entity_id": category_name,
                        "evaluation_date": eval_date_str,
                        "score_gap_rank_1_to_10": gap,
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
        """Fund detail page — 12 FUND_*_V1 templates + 4 preserved fallbacks."""
        results: list[dict] = []
        eval_date_str = str(evaluation_date)

        def _base(fund_name: str = "") -> dict:
            return {
                "entity_id": schemecode,
                "entity_name": fund_name,
                "evaluation_date": eval_date_str,
            }

        name_row = self.db.execute(text("""
            SELECT fund_name FROM selfmade_ranking_snapshot
            WHERE schemecode = :sc ORDER BY snapshot_date DESC LIMIT 1
        """), {"sc": schemecode}).fetchone()
        fund_name = name_row[0] if name_row else str(schemecode)

        # ── Group 1: Holdings ──────────────────────────────────────────────────
        holding_row = self.db.execute(text("""
            SELECT COUNT(*), MAX(as_of_date) FROM selfmade_portfolio_holding
            WHERE scheme_id = :sc
        """), {"sc": schemecode}).fetchone()
        holding_count = int(holding_row[0]) if holding_row else 0
        holdings_date = holding_row[1] if holding_row else None

        if holding_count == 0:
            results.append({"template_id": "FUND_HOLDINGS_AVAIL_NONE_V1", "variables": _base(fund_name)})
        else:
            top_holdings = self.db.execute(text("""
                SELECT sm.company_name, ph.holding_weight_pct
                FROM selfmade_portfolio_holding ph
                JOIN selfmade_security_master sm ON sm.id = ph.security_id
                WHERE ph.scheme_id = :sc AND ph.as_of_date = :dt
                ORDER BY ph.holding_weight_pct DESC LIMIT 5
            """), {"sc": schemecode, "dt": holdings_date}).fetchall()

            if holding_count < 5:
                results.append({
                    "template_id": "FUND_TOP_HOLDINGS_LESS_THAN_5_V1",
                    "variables": {**_base(fund_name), "holding_count": holding_count,
                                  "as_of_date": str(holdings_date)},
                })
            else:
                top5_pct = round(sum(float(r[1] or 0) for r in top_holdings), 2)
                hv = {**_base(fund_name), "top_5_weight_pct": top5_pct,
                      "holding_count": holding_count, "as_of_date": str(holdings_date)}
                for i, r in enumerate(top_holdings, start=1):
                    hv[f"holding_{i}_name"] = r[0]
                    hv[f"holding_{i}_weight_pct"] = round(float(r[1] or 0), 2)
                results.append({"template_id": "FUND_TOP_HOLDINGS_V1", "variables": hv})

        # ── Group 2: Sectors ───────────────────────────────────────────────────
        if holding_count > 0:
            sector_rows = self.db.execute(text("""
                SELECT sm.sector, SUM(ph.holding_weight_pct) AS sector_wt
                FROM selfmade_portfolio_holding ph
                JOIN selfmade_security_master sm ON sm.id = ph.security_id
                WHERE ph.scheme_id = :sc AND ph.as_of_date = :dt AND sm.sector IS NOT NULL
                GROUP BY sm.sector ORDER BY sector_wt DESC
            """), {"sc": schemecode, "dt": holdings_date}).fetchall()

            if len(sector_rows) < 3:
                results.append({
                    "template_id": "FUND_SECTORS_UNAVAILABLE_V1",
                    "variables": {**_base(fund_name), "sector_count": len(sector_rows)},
                })
            else:
                total_sector_wt = sum(float(r[1] or 0) for r in sector_rows)
                sectors_to_80, cumulative = 0, 0.0
                for r in sector_rows:
                    cumulative += float(r[1] or 0)
                    sectors_to_80 += 1
                    if total_sector_wt > 0 and cumulative / total_sector_wt >= 0.80:
                        break
                profile = (
                    "concentrated" if sectors_to_80 <= SECTORS_TO_80_CONCENTRATED
                    else "diversified" if sectors_to_80 >= SECTORS_TO_80_MODERATE
                    else "moderate"
                )
                top3 = sector_rows[:3]
                sector_v = {
                    **_base(fund_name),
                    "sector_1": top3[0][0], "sector_1_weight_pct": round(float(top3[0][1] or 0), 2),
                    "sector_2": top3[1][0], "sector_2_weight_pct": round(float(top3[1][1] or 0), 2),
                    "sector_3": top3[2][0], "sector_3_weight_pct": round(float(top3[2][1] or 0), 2),
                    "top_3_sector_weight_pct": round(sum(float(r[1] or 0) for r in top3), 2),
                }
                results.append({"template_id": "FUND_TOP_SECTORS_V1", "variables": sector_v})
                results.append({
                    "template_id": "FUND_SECTORS_TO_80_V1",
                    "variables": {
                        **sector_v, "sectors_to_80": sectors_to_80,
                        "cumulative_sector_weight_pct": round(cumulative, 2),
                        "sector_profile_label": profile,
                    },
                })

        # ── Group 3: 3Y information ratio (percentile-based 3-way split) ───────
        metrics_row = self.db.execute(text("""
            SELECT information_ratio_3yr, sharpe_ratio_3yr, sortino_ratio_3yr
            FROM selfmade_scheme_metrics WHERE schemecode = :sc
        """), {"sc": schemecode}).fetchone()

        snap_row = self.db.execute(text("""
            SELECT s.rank_in_category, sr.total_in_category, s.category,
                   s.composite_score_v2, sr.pct_ir_3yr, s.rank_delta_6m
            FROM selfmade_ranking_snapshot s
            LEFT JOIN selfmade_scheme_ranking sr ON sr.schemecode = s.schemecode
            WHERE s.schemecode = :sc ORDER BY s.snapshot_date DESC LIMIT 1
        """), {"sc": schemecode}).fetchone()

        ir3 = float(metrics_row[0]) if metrics_row and metrics_row[0] is not None else None
        sortino3 = float(metrics_row[2]) if metrics_row and metrics_row[2] is not None else None
        pct_ir = float(snap_row[4]) if snap_row and snap_row[4] is not None else None
        rank_ic = int(snap_row[0]) if snap_row else None
        total_ic = int(snap_row[1]) if snap_row else None

        if ir3 is None:
            results.append({"template_id": "FUND_3Y_IR_INSUFFICIENT_HISTORY_V1", "variables": _base(fund_name)})
        else:
            pct_ir_eff = pct_ir if pct_ir is not None else 50.0
            ir_v = {**_base(fund_name), "ir_3y": round(ir3, 4),
                    "ir_3y_percentile": round(pct_ir_eff, 0)}
            if pct_ir_eff >= IR_PERCENTILE_STRONG:
                results.append({"template_id": "FUND_3Y_IR_TOP_TIER_V1", "variables": ir_v})
            elif pct_ir_eff >= IR_PERCENTILE_WEAK:
                results.append({"template_id": "FUND_3Y_IR_ACCEPTABLE_V1", "variables": ir_v})
            else:
                results.append({"template_id": "FUND_3Y_IR_WEAK_V1", "variables": ir_v})

            # ── Group 4: 3Y overall performance scorecard (GOOD_3Y rule) ────────
            outperf_rows = self.db.execute(text("""
                SELECT informationratio FROM ratio_3year_monthlyret
                WHERE schemecode = :sc AND informationratio IS NOT NULL
                ORDER BY ratiodate DESC LIMIT 12
            """), {"sc": schemecode}).fetchall()
            outperf_vals = [float(r[0]) for r in outperf_rows]
            outperf_pct = (
                round(sum(1 for v in outperf_vals if v > 0) / len(outperf_vals) * 100, 1)
                if outperf_vals else None
            )
            good_3y = (
                pct_ir_eff >= IR_PERCENTILE_STRONG
                and sortino3 is not None and sortino3 > 0.5
                and outperf_pct is not None and outperf_pct >= OUTPERFORMANCE_RATIO_STRONG
            )
            perf_v = {
                **_base(fund_name), "ir_3y": round(ir3, 4),
                "sortino_3y": round(sortino3, 4) if sortino3 is not None else "n/a",
                "outperformance_ratio_3y_pct": outperf_pct if outperf_pct is not None else "n/a",
                "rank_in_category": rank_ic, "total_in_category": total_ic,
            }
            if good_3y:
                results.append({"template_id": "FUND_3Y_PERFORMANCE_STRONG_V1", "variables": perf_v})
            else:
                positive = "3Y IR is in the top tier" if pct_ir_eff >= IR_PERCENTILE_STRONG else "3Y IR is acceptable"
                concern = (
                    "Sortino is below 0.5" if sortino3 is None or sortino3 <= 0.5
                    else "outperformance ratio is below the 60% threshold" if outperf_pct is None or outperf_pct < OUTPERFORMANCE_RATIO_STRONG
                    else "not all risk-adjusted metrics agree"
                )
                results.append({
                    "template_id": "FUND_3Y_PERFORMANCE_MIXED_V1",
                    "variables": {**perf_v, "positive_metric_summary": positive, "negative_metric_summary": concern},
                })

        # ── Group 5: Trend (rank + IR slope + improvement metric together) ─────
        ir_slope = compute_ir_slope_proxy(self.db, schemecode)
        improvement_metric = compute_improvement_metric(self.db, schemecode)
        rank_delta_6m = int(snap_row[5]) if snap_row and snap_row[5] is not None else None

        if ir_slope is None or improvement_metric is None:
            results.append({"template_id": "FUND_TREND_INSUFFICIENT_DATA_V1", "variables": _base(fund_name)})
        elif rank_delta_6m is None:
            results.append({"template_id": "FUND_TREND_INSUFFICIENT_DATA_V1", "variables": _base(fund_name)})
        else:
            monthly_rows = self.db.execute(text("""
                SELECT informationratio FROM ratio_3year_monthlyret
                WHERE schemecode = :sc AND informationratio IS NOT NULL
                ORDER BY ratiodate DESC LIMIT 12
            """), {"sc": schemecode}).fetchall()
            vals = [float(r[0]) for r in monthly_rows]
            latest_6m = round(sum(vals[:6]) / len(vals[:6]), 4) if len(vals) >= 6 else None
            prior_6m = round(sum(vals[6:12]) / len(vals[6:12]), 4) if len(vals) >= 12 else None

            trend_v = {
                **_base(fund_name),
                "ir_slope_3y": round(ir_slope, 4),
                "improvement_metric": round(improvement_metric, 4),
                "rank_delta_6m": rank_delta_6m,
                "latest_6m_avg_rolling_ir": latest_6m if latest_6m is not None else "n/a",
                "previous_6m_avg_rolling_ir": prior_6m if prior_6m is not None else "n/a",
            }
            if ir_slope > IR_SLOPE_IMPROVING and improvement_metric > 0 and rank_delta_6m <= -RANK_IMPROVEMENT_THRESHOLD:
                results.append({
                    "template_id": "FUND_TREND_IMPROVING_V1",
                    "variables": {**trend_v, "rank_improvement_abs": abs(rank_delta_6m)},
                })
            elif ir_slope < IR_SLOPE_WEAKENING and improvement_metric < 0 and rank_delta_6m >= RANK_IMPROVEMENT_THRESHOLD:
                results.append({
                    "template_id": "FUND_TREND_WEAKENING_V1",
                    "variables": {**trend_v, "rank_decline_abs": rank_delta_6m},
                })
            else:
                positive_ind = "3Y IR slope is positive" if ir_slope > 0 else "rank improved recently" if rank_delta_6m < 0 else "improvement metric is positive" if improvement_metric > 0 else "no strong positive indicator"
                negative_ind = "rank has not improved" if rank_delta_6m >= 0 else "3Y IR slope is not positive" if ir_slope <= 0 else "improvement metric has not confirmed it"
                results.append({
                    "template_id": "FUND_TREND_MIXED_V1",
                    "variables": {**trend_v, "positive_trend_indicator": positive_ind,
                                  "negative_trend_indicator": negative_ind},
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
        Fund comparison page — 8 CMP_*_V1 templates + 1 preserved fallback.

        Sector overlap and a separate "overall best" slot are dropped (not in
        the new template set — category leader below already covers "who's
        ahead"). Each template fires at most once.
        """
        results: list[dict] = []
        fired: set[str] = set()
        eval_date_str = str(evaluation_date)

        def _add(template_id: str, variables: dict) -> None:
            if template_id not in fired:
                fired.add(template_id)
                results.append({"template_id": template_id, "variables": {
                    **variables, "evaluation_date": eval_date_str,
                }})

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
                    "sc": row[0], "name": row[1], "category": row[2],
                    "rank": int(row[3]) if row[3] is not None else None,
                    "rank_delta": int(row[4]) if row[4] is not None else None,
                    "score": float(row[5]) if row[5] is not None else 0.0,
                    "ir": float(row[6]) if row[6] is not None else None,
                    "ir_slope": float(row[7]) if row[7] is not None else None,
                })

        if not fund_data:
            return results

        is_two_fund = len(schemecodes) == 2
        entity_id = "_".join(str(s) for s in sorted(schemecodes))

        # ── 1. Holdings overlap ───────────────────────────────────────────────
        overlap = get_overlap_metrics(self.db, schemecodes)
        wo = overlap["weighted_overlap"]
        has_overlap_data = wo > 0 or overlap["common_count"] > 0
        overlap_band = (
            "very high" if wo >= HOLDINGS_OVERLAP_VERY_HIGH
            else "high" if wo >= HOLDINGS_OVERLAP_HIGH
            else "moderate" if wo >= HOLDINGS_OVERLAP_MODERATE
            else "low"
        )

        if not has_overlap_data:
            _add("CMP_HOLDINGS_OVERLAP_UNAVAILABLE_V1", {"entity_id": entity_id})
        elif is_two_fund:
            _add("CMP_HOLDINGS_OVERLAP_TWO_FUNDS_V1", {
                "entity_id": entity_id,
                "fund_a": fund_data[0]["name"], "fund_b": fund_data[1]["name"],
                "weighted_overlap_pct": round(wo, 2),
                "common_holdings_count": overlap["common_count"],
                "jaccard_overlap_pct": round(overlap["jaccard"], 2),
                "overlap_band": overlap_band,
            })
        else:
            sc_to_name = {f["sc"]: f["name"] for f in fund_data}
            pairs = overlap.get("pairs") or []
            max_pair = max(pairs, key=lambda p: p["weighted_overlap"]) if pairs else None
            min_pair = min(pairs, key=lambda p: p["weighted_overlap"]) if pairs else None

            def _pair_name(p: dict | None) -> str:
                if not p:
                    return "—"
                a = sc_to_name.get(p["fund_a"], str(p["fund_a"]))
                b = sc_to_name.get(p["fund_b"], str(p["fund_b"]))
                return f"{a} / {b}"

            _add("CMP_HOLDINGS_OVERLAP_MULTI_FUND_V1", {
                "entity_id": entity_id,
                "avg_pairwise_overlap_pct": round(wo, 2),
                "max_pair_name": _pair_name(max_pair),
                "max_pair_overlap_pct": round(max_pair["weighted_overlap"], 2) if max_pair else 0.0,
                "min_pair_name": _pair_name(min_pair),
                "min_pair_overlap_pct": round(min_pair["weighted_overlap"], 2) if min_pair else 0.0,
                "common_to_all_count": overlap.get("common_to_all_count", 0),
            })

        # ── 2. Category / clear leader (merges old category + best-overall) ────
        categories = {f["category"] for f in fund_data if f["category"]}
        scores = [f["score"] for f in fund_data]
        score_gap = round(max(scores) - min(scores), 2) if scores else 0.0
        leader = max(fund_data, key=lambda f: f["score"])
        others = [f for f in fund_data if f["sc"] != leader["sc"]]
        metrics_won = 0
        metric_wins: list[str] = []
        for other in others:
            if leader["ir"] is not None and other["ir"] is not None and leader["ir"] > other["ir"]:
                metrics_won += 1
                metric_wins.append("3Y IR")
            if leader["rank"] is not None and other["rank"] is not None and leader["rank"] < other["rank"]:
                metrics_won += 1
                metric_wins.append("rank")
        cat = leader["category"] or (next(iter(categories)) if categories else "")

        if len(categories) == 1 and score_gap >= SCORE_LEADER_GAP_THRESHOLD and metrics_won >= 2:
            _add("CMP_CLEAR_LEADER_V1", {
                "entity_id": entity_id, "leader_fund": leader["name"], "category": cat,
                "score_gap": score_gap, "metric_win_summary": ", ".join(metric_wins) or "composite score",
                "leader_current_rank": leader["rank"],
            })
        else:
            ir_leader_name = max(
                (f for f in fund_data if f["ir"] is not None), key=lambda f: f["ir"], default=None,
            )
            slope_leader_name = max(
                (f for f in fund_data if f["ir_slope"] is not None), key=lambda f: f["ir_slope"], default=None,
            )
            _add("CMP_NO_CLEAR_LEADER_V1", {
                "entity_id": entity_id, "score_gap": score_gap,
                "ir_leader": ir_leader_name["name"] if ir_leader_name else "—",
                "trend_leader": slope_leader_name["name"] if slope_leader_name else "—",
                "differentiated_fund": leader["name"],
            })

        # ── 3. 3Y IR leadership ────────────────────────────────────────────────
        funds_with_ir = [f for f in fund_data if f["ir"] is not None]
        if funds_with_ir:
            funds_sorted_ir = sorted(funds_with_ir, key=lambda f: f["ir"], reverse=True)
            ir_leader = funds_sorted_ir[0]
            second = funds_sorted_ir[1] if len(funds_sorted_ir) >= 2 else None
            gap = (ir_leader["ir"] - second["ir"]) if second else 0.0

            funds_with_slope = [f for f in fund_data if f["ir_slope"] is not None]
            slope_leader = max(funds_with_slope, key=lambda f: f["ir_slope"], default=None)
            ir_conflict = (
                slope_leader is not None and slope_leader["sc"] != ir_leader["sc"]
                and slope_leader["ir_slope"] > IR_SLOPE_IMPROVING
            )

            if ir_conflict:
                _add("CMP_3Y_IR_CONFLICT_V1", {
                    "entity_id": entity_id,
                    "ir_leader": ir_leader["name"], "leader_ir_3y": round(ir_leader["ir"], 4),
                    "trend_leader": slope_leader["name"],
                    "trend_reason": f"IR slope {slope_leader['ir_slope']:+.4f}/month",
                })
            else:
                _add("CMP_BETTER_3Y_IR_V1", {
                    "entity_id": entity_id,
                    "ir_leader": ir_leader["name"], "leader_ir_3y": round(ir_leader["ir"], 4),
                    "second_fund": second["name"] if second else "—",
                    "second_ir_3y": round(second["ir"], 4) if second and second["ir"] is not None else "n/a",
                    "ir_gap": round(gap, 4),
                })

        # ── 4. Recent improvement leader ────────────────────────────────────────
        funds_with_slope = [f for f in fund_data if f["ir_slope"] is not None]
        if funds_with_slope:
            top = max(funds_with_slope, key=lambda f: f["ir_slope"])
            if top["ir_slope"] > 0:
                _add("CMP_RECENT_IMPROVEMENT_LEADER_V1", {
                    "entity_id": entity_id, "trend_leader": top["name"],
                    "rank_improvement_abs": abs(top["rank_delta"]) if top["rank_delta"] and top["rank_delta"] < 0 else 0,
                    "ir_slope_3y": round(top["ir_slope"], 4),
                    "improvement_metric": round(top["ir_slope"], 4),
                    "recent_ir_change": round(top["ir_slope"], 4),
                })

        # ── 5. Laggard ────────────────────────────────────────────────────────
        if len(fund_data) >= 2:
            laggard = min(fund_data, key=lambda f: f["score"])
            weak_conditions = 0
            if laggard["ir"] is not None and laggard["ir"] < 0:
                weak_conditions += 1
            if laggard["ir_slope"] is not None and laggard["ir_slope"] < IR_SLOPE_WEAKENING:
                weak_conditions += 1
            if laggard["rank_delta"] is not None and laggard["rank_delta"] >= RANK_IMPROVEMENT_THRESHOLD:
                weak_conditions += 1

            if weak_conditions >= 2:
                ir_vals = [f["ir"] for f in fund_data if f["ir"] is not None]
                percentile = (
                    round(sum(1 for v in ir_vals if v <= laggard["ir"]) / len(ir_vals) * 100, 0)
                    if laggard["ir"] is not None and ir_vals else 50
                )
                _add("CMP_LAGGARD_V1", {
                    "entity_id": entity_id, "laggard_fund": laggard["name"],
                    "laggard_ir_3y": round(laggard["ir"], 4) if laggard["ir"] is not None else "n/a",
                    "laggard_ir_percentile": percentile,
                    "laggard_ir_slope_3y": round(laggard["ir_slope"], 4) if laggard["ir_slope"] is not None else "n/a",
                    "laggard_rank_delta": laggard["rank_delta"] if laggard["rank_delta"] is not None else "n/a",
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
