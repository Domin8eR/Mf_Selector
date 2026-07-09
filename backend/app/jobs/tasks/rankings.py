"""Celery task: generate a ranking snapshot for a category + rule version."""

from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Any

from app.jobs.celery_app import celery_app
from app.quant.metrics import percentile_rank

logger = logging.getLogger(__name__)

CALC_VERSION = "1.0"


def _session():
    from app.core.db import SessionLocal
    return SessionLocal()


@celery_app.task(name="tasks.generate_ranking_snapshot", bind=True, max_retries=3)
def generate_ranking_snapshot(
    self,
    category_id: str,
    rule_version_id: str,
    evaluation_date_iso: str,
    data_version_id: int,
) -> dict[str, Any]:
    """
    Score and rank all active scheme_plans in a category using the
    given rule_version's components and the latest metric_value_snapshots.

    Steps:
    1. Load rule_components (metric_id, weight, direction).
    2. Load metric_value_snapshot rows for the evaluation_date.
    3. Percentile-rank each metric cross-sectionally.
    4. Compute weighted score = Σ(normalised_i × weight_i).
    5. Rank by score descending; compute rank_change vs. prior run.
    6. Insert ranking_run + ranking_result + ranking_component_contribution.
    """
    evaluation_date = date.fromisoformat(evaluation_date_iso)
    db = _session()
    try:
        from sqlalchemy import text

        # ── Load rule components ─────────────────────────────────────────
        components = db.execute(
            text(
                "SELECT metric_id, weight, direction "
                "FROM rule_component WHERE rule_version_id = :rv "
                "ORDER BY display_order"
            ),
            {"rv": rule_version_id},
        ).fetchall()

        if not components:
            logger.warning("no components found for rule_version %s", rule_version_id)
            return {"status": "no_components"}

        weights = {r[0]: float(r[1]) for r in components}
        directions = {r[0]: r[2] for r in components}

        # ── Load metric snapshots ────────────────────────────────────────
        mv_rows = db.execute(
            text(
                "SELECT mvs.scheme_plan_id, mvs.metric_id, mvs.value "
                "FROM metric_value_snapshot mvs "
                "JOIN scheme_plan sp ON sp.id = mvs.scheme_plan_id "
                "WHERE sp.category_id = :cat "
                "AND sp.is_active = true "
                "AND mvs.evaluation_date = :d "
                "AND mvs.metric_id = ANY(:mids)"
            ),
            {
                "cat": category_id,
                "d": evaluation_date,
                "mids": list(weights.keys()),
            },
        ).fetchall()

        # Build fund → {metric_id: value} map
        fund_metrics: dict[str, dict[str, float | None]] = {}
        for sp_id, mid, val in mv_rows:
            fund_metrics.setdefault(sp_id, {})[mid] = (
                float(val) if val is not None else None
            )

        if not fund_metrics:
            logger.warning("no metric data found for %s / %s", category_id, evaluation_date_iso)
            return {"status": "no_metric_data"}

        fund_ids = list(fund_metrics.keys())

        # ── Cross-sectional percentile ranks ─────────────────────────────
        normed: dict[str, dict[str, float]] = {}
        for mid, direction in directions.items():
            vals = [
                (fid, fund_metrics[fid][mid])
                for fid in fund_ids
                if fund_metrics[fid].get(mid) is not None
            ]
            universe = [v for _, v in vals]
            for fid, val in vals:
                normed.setdefault(fid, {})[mid] = percentile_rank(
                    val, universe, direction  # type: ignore[arg-type]
                )

        # ── Weighted scores ───────────────────────────────────────────────
        scores = {
            fid: sum(
                normed.get(fid, {}).get(mid, 0.0) * w
                for mid, w in weights.items()
            )
            for fid in fund_ids
        }
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        # ── Prior run ranks for rank_change ──────────────────────────────
        prior = db.execute(
            text(
                "SELECT rr.scheme_plan_id, rr.rank "
                "FROM ranking_result rr "
                "JOIN ranking_run run ON run.id = rr.ranking_run_id "
                "WHERE run.category_id = :cat "
                "AND run.rule_version_id = :rv "
                "AND run.evaluation_date < :d "
                "ORDER BY run.evaluation_date DESC, rr.rank LIMIT 1000"
            ),
            {"cat": category_id, "rv": rule_version_id, "d": evaluation_date},
        ).fetchall()
        prior_ranks: dict[str, int] = {r[0]: r[1] for r in prior}

        # ── Status label ─────────────────────────────────────────────────
        n = len(ranked)
        def _status(rank: int) -> str:
            pct = rank / n if n > 0 else 1.0
            if pct <= 0.20: return "Strong"
            if pct <= 0.40: return "Good"
            if pct <= 0.60: return "Neutral"
            if pct <= 0.80: return "Watch"
            return "Weak"

        # ── Insert run + results ──────────────────────────────────────────
        run_id = f"RR-{category_id}-{evaluation_date_iso.replace('-', '')}-{uuid.uuid4().hex[:6].upper()}"
        db.execute(
            text(
                "INSERT INTO ranking_run "
                "(id, rule_version_id, category_id, evaluation_date, "
                "data_version_id, calculation_version, scheme_count) "
                "VALUES (:id, :rv, :cat, :d, :dv, :cv, :sc)"
            ),
            dict(id=run_id, rv=rule_version_id, cat=category_id,
                 d=evaluation_date, dv=data_version_id,
                 cv=CALC_VERSION, sc=len(ranked)),
        )

        for rank, (fid, score) in enumerate(ranked, 1):
            prev = prior_ranks.get(fid)
            change = (prev - rank) if prev else None

            res = db.execute(
                text(
                    "INSERT INTO ranking_result "
                    "(ranking_run_id, scheme_plan_id, rank, score, prev_rank, "
                    "rank_change, status_label) "
                    "VALUES (:run, :sp, :rk, :sc, :pr, :rc, :sl) "
                    "RETURNING id"
                ),
                dict(run=run_id, sp=fid, rk=rank,
                     sc=round(score * 100, 4), pr=prev, rc=change,
                     sl=_status(rank)),
            )
            result_id = res.fetchone()[0]

            for mid, w in weights.items():
                raw = fund_metrics.get(fid, {}).get(mid)
                norm = normed.get(fid, {}).get(mid)
                contrib = (norm * w) if norm is not None else None
                db.execute(
                    text(
                        "INSERT INTO ranking_component_contribution "
                        "(ranking_result_id, metric_id, raw_value, "
                        "normalized_value, weight, contribution) "
                        "VALUES (:rid, :mid, :rv2, :nv, :w, :c)"
                    ),
                    dict(rid=result_id, mid=mid, rv2=raw,
                         nv=norm, w=w, c=contrib),
                )

        db.commit()
        logger.info(
            "ranking snapshot generated",
            run_id=run_id, category=category_id,
            eval_date=evaluation_date_iso, funds=len(ranked),
        )
        return {"run_id": run_id, "funds_ranked": len(ranked), "status": "ok"}

    except Exception as exc:
        db.rollback()
        logger.exception("ranking task failed", exc_info=exc)
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()
