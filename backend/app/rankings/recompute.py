"""
The one canonical ranking recompute pipeline.

Replaces two things that used to disagree:
  - scripts/step4_scheme_ranking.py's own hardcoded pandas formula
    (never read selfmade_rule_component at all — a genuine governance gap).
  - scripts/seed_category_rankings.py's real rule-engine formula, but
    scoped to only 3 of the 31 real bucket_36 categories.

recompute_all_rankings() reads the target rule_version's real
selfmade_rule_component rows (metric_column, metric_source, direction,
weight), computes percentile_rank (app.quant.metrics — the one canonical
implementation, not a fourth copy) per component, grouped by
category_taxonomy_current.bucket_36 (the real 31-category taxonomy, not
the old 41-value granular category string), for every scheme with a
bucket_36. Writes selfmade_ranking_snapshot + selfmade_ranking_contribution.

Honest-degradation rule: a fund's composite_score_v2 is only ever computed
if it has a real (non-null) value for EVERY one of the rule version's
components. Partial data does not get rescaled or defaulted to a neutral
percentile (that would be a fabricated score) — it gets no snapshot row at
all this run, same as any other zero-coverage category. This is why most
Hybrid/Passive funds (no IR/Sharpe data) correctly produce no ranked row,
not an error and not a fabricated score.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.quant.metrics import percentile_rank
from app.rankings.metric_vocab import METRIC_VOCAB

SORT_BASIS = "RULE_ENGINE_V1"


def _resolve_rule_version_id(db: Session, rule_version_id: int | None) -> int | None:
    if rule_version_id is not None:
        return rule_version_id
    row = db.execute(text(
        "SELECT id FROM selfmade_rule_version WHERE is_active = true ORDER BY id DESC LIMIT 1"
    )).fetchone()
    return row[0] if row else None


def recompute_all_rankings(
    db: Session,
    rule_version_id: int | None = None,
    evaluation_date: date | None = None,
) -> dict:
    """
    Score every fund with a real category_taxonomy_current.bucket_36 against
    the target rule version's components, and persist the result.

    Returns a summary dict: {status, rule_version_id, evaluation_date,
    funds_scored, funds_skipped_insufficient_data, categories_scored}.
    """
    evaluation_date = evaluation_date or date.today()

    resolved_rv = _resolve_rule_version_id(db, rule_version_id)
    if resolved_rv is None:
        return {
            "status": "no_active_rule_version",
            "rule_version_id": None,
            "evaluation_date": str(evaluation_date),
            "funds_scored": 0,
            "funds_skipped_insufficient_data": 0,
            "categories_scored": 0,
        }

    components = db.execute(text("""
        SELECT id, metric_column, metric_source, direction, weight
        FROM selfmade_rule_component
        WHERE rule_version_id = :rv
        ORDER BY sort_order
    """), {"rv": resolved_rv}).fetchall()

    if not components:
        return {
            "status": "no_components",
            "rule_version_id": resolved_rv,
            "evaluation_date": str(evaluation_date),
            "funds_scored": 0,
            "funds_skipped_insufficient_data": 0,
            "categories_scored": 0,
        }

    # Defense: never interpolate a metric_source/metric_column into SQL
    # unless it's in the vetted vocabulary (Rule Playground already
    # validates against this at authoring time — this is a second check,
    # not the only one).
    for _, col, src, _direction, _weight in components:
        vocab_entry = METRIC_VOCAB.get(col)
        if vocab_entry is None or vocab_entry["source"] != src:
            raise ValueError(
                f"Rule component metric_column={col!r} metric_source={src!r} "
                f"is not in the vetted METRIC_VOCAB — refusing to build a query from it."
            )

    # ── Real taxonomy: schemecode -> bucket_36, for every scheme that has one ──
    taxonomy_rows = db.execute(text("""
        SELECT schemecode, bucket_36 FROM category_taxonomy_current
        WHERE bucket_36 IS NOT NULL AND bucket_36 <> ''
    """)).fetchall()
    bucket_by_scheme: dict[int, str] = {r[0]: r[1] for r in taxonomy_rows}
    schemecodes = list(bucket_by_scheme.keys())

    if not schemecodes:
        return {
            "status": "no_taxonomy_data",
            "rule_version_id": resolved_rv,
            "evaluation_date": str(evaluation_date),
            "funds_scored": 0,
            "funds_skipped_insufficient_data": 0,
            "categories_scored": 0,
        }

    name_rows = db.execute(text("""
        SELECT scheme_id::integer, scheme_name FROM altstreet_scheme_master
    """)).fetchall()
    name_by_scheme: dict[int, str] = {r[0]: r[1] for r in name_rows}

    # ── Fetch each component's raw value for every scheme with a bucket_36 ──
    # metric_source/metric_column are vetted above; this is the ONLY place
    # they're interpolated (never taken from unvalidated request input).
    raw_by_component: dict[int, dict[int, float]] = {}
    for comp_id, col, src, _direction, _weight in components:
        if src == "selfmade_ranking_snapshot":
            # Self-referential metric (e.g. rank_delta_6m as a rule input) —
            # use the most recent PRIOR snapshot row for the SAME bucket_36
            # category, never this run's own not-yet-computed values, and
            # never a row from a different category naming (e.g. the old
            # "Equity — Large Cap" legacy string) — comparing across
            # different category groupings/formulas would be apples-to-
            # oranges even though both are real dates.
            rows = db.execute(text(f"""
                SELECT DISTINCT ON (s.schemecode) s.schemecode, s.{col}
                FROM selfmade_ranking_snapshot s
                JOIN category_taxonomy_current t
                    ON t.schemecode = s.schemecode AND t.bucket_36 = s.category
                WHERE s.schemecode = ANY(:codes) AND s.snapshot_date < :ed
                ORDER BY s.schemecode, s.snapshot_date DESC
            """), {"codes": schemecodes, "ed": evaluation_date}).fetchall()
        else:
            rows = db.execute(text(f"""
                SELECT schemecode, {col} FROM {src} WHERE schemecode = ANY(:codes)
            """), {"codes": schemecodes}).fetchall()
        raw_by_component[comp_id] = {
            r[0]: float(r[1]) for r in rows if r[1] is not None
        }

    # ── Group by real bucket_36 category ──
    schemes_by_bucket: dict[str, list[int]] = {}
    for sc, bucket in bucket_by_scheme.items():
        schemes_by_bucket.setdefault(bucket, []).append(sc)

    # ── Percentile rank per component, per bucket, direction-aware ──
    pct_by_scheme: dict[int, dict[int, float]] = {}
    for bucket, codes in schemes_by_bucket.items():
        for comp_id, col, src, direction, weight in components:
            raw_map = raw_by_component[comp_id]
            universe = [raw_map[sc] for sc in codes if sc in raw_map]
            if not universe:
                continue
            for sc in codes:
                if sc not in raw_map:
                    continue
                pct = percentile_rank(raw_map[sc], universe, direction) * 100.0
                pct_by_scheme.setdefault(sc, {})[comp_id] = pct

    # ── Weighted composite score — ALL components required, no fabrication ──
    composite_by_scheme: dict[int, float] = {}
    for sc in schemecodes:
        comp_pcts = pct_by_scheme.get(sc, {})
        if len(comp_pcts) != len(components):
            continue  # insufficient data — honestly skipped, not defaulted
        composite_by_scheme[sc] = sum(
            comp_pcts[comp_id] * float(weight) for comp_id, _, _, _, weight in components
        )

    # ── Rank within each bucket (RANK() "min"-tie semantics, real ties share) ──
    rank_by_scheme: dict[int, int] = {}
    for bucket, codes in schemes_by_bucket.items():
        scored = sorted(
            ((sc, composite_by_scheme[sc]) for sc in codes if sc in composite_by_scheme),
            key=lambda x: x[1], reverse=True,
        )
        prev_score, prev_rank = None, 0
        for i, (sc, score) in enumerate(scored, start=1):
            rank = i if score != prev_score else prev_rank
            rank_by_scheme[sc] = rank
            prev_score, prev_rank = score, rank

    scored_schemecodes = list(composite_by_scheme.keys())
    if not scored_schemecodes:
        return {
            "status": "no_fund_had_complete_data",
            "rule_version_id": resolved_rv,
            "evaluation_date": str(evaluation_date),
            "funds_scored": 0,
            "funds_skipped_insufficient_data": len(schemecodes),
            "categories_scored": 0,
        }

    # ── Prior snapshot rank, for an honest rank_delta_6m (null if none exists) ──
    # Must match on the SAME category value as today's row (bucket_by_scheme),
    # not just an earlier date — a prior row stored under a different naming
    # (e.g. the legacy "Equity — Large Cap" synthetic-history rows) used a
    # different grouping and a different, disconnected formula; comparing
    # against it would silently produce a real-looking but meaningless delta.
    # Looped per-bucket (one category value per query) so each schemecode is
    # only ever compared against a PRIOR row under its own real category.
    prior_rank_by_scheme: dict[int, int] = {}
    scored_by_bucket: dict[str, list[int]] = {}
    for sc in scored_schemecodes:
        scored_by_bucket.setdefault(bucket_by_scheme[sc], []).append(sc)
    for bucket, codes in scored_by_bucket.items():
        prior_rows = db.execute(text("""
            SELECT DISTINCT ON (schemecode) schemecode, rank_in_category
            FROM selfmade_ranking_snapshot
            WHERE schemecode = ANY(:codes) AND category = :bucket AND snapshot_date < :ed
            ORDER BY schemecode, snapshot_date DESC
        """), {"codes": codes, "bucket": bucket, "ed": evaluation_date}).fetchall()
        prior_rank_by_scheme.update({r[0]: r[1] for r in prior_rows})

    # ── IR raw value for the snapshot's own point-in-time column ──
    ir_component = next((c for c in components if c[1] == "information_ratio_3yr"), None)
    ir_raw_by_scheme = raw_by_component.get(ir_component[0], {}) if ir_component else {}

    # ── Bulk upsert selfmade_ranking_snapshot ──
    snapshot_rows = []
    for sc in scored_schemecodes:
        prior_rank = prior_rank_by_scheme.get(sc)
        new_rank = rank_by_scheme[sc]
        snapshot_rows.append({
            "snapshot_date": evaluation_date,
            "category": bucket_by_scheme[sc],
            "schemecode": sc,
            "fund_name": name_by_scheme.get(sc, f"Fund {sc}"),
            "rank_in_category": new_rank,
            "composite_score_v2": round(composite_by_scheme[sc], 4),
            "information_ratio_3yr": ir_raw_by_scheme.get(sc),
            "rank_delta_6m": (prior_rank - new_rank) if prior_rank is not None else None,
            "sort_basis": SORT_BASIS,
        })

    if snapshot_rows:
        db.execute(text("""
            INSERT INTO selfmade_ranking_snapshot
                (snapshot_date, category, schemecode, fund_name, rank_in_category,
                 composite_score_v2, information_ratio_3yr, rank_delta_6m, sort_basis)
            VALUES (:snapshot_date, :category, :schemecode, :fund_name, :rank_in_category,
                    :composite_score_v2, :information_ratio_3yr, :rank_delta_6m, :sort_basis)
            ON CONFLICT (snapshot_date, category, schemecode) DO UPDATE SET
                fund_name = EXCLUDED.fund_name,
                rank_in_category = EXCLUDED.rank_in_category,
                composite_score_v2 = EXCLUDED.composite_score_v2,
                information_ratio_3yr = EXCLUDED.information_ratio_3yr,
                rank_delta_6m = EXCLUDED.rank_delta_6m,
                sort_basis = EXCLUDED.sort_basis
        """), snapshot_rows)

    # ── Look up the snapshot ids we just wrote (bulk executemany can't
    # reliably return per-row ids), then bulk upsert contributions ──
    snap_id_rows = db.execute(text("""
        SELECT id, schemecode, category FROM selfmade_ranking_snapshot
        WHERE snapshot_date = :ed AND schemecode = ANY(:codes)
    """), {"ed": evaluation_date, "codes": scored_schemecodes}).fetchall()
    snap_id_by_scheme_category = {(r[1], r[2]): r[0] for r in snap_id_rows}

    contribution_rows = []
    for sc in scored_schemecodes:
        snap_id = snap_id_by_scheme_category.get((sc, bucket_by_scheme[sc]))
        if snap_id is None:
            continue
        for comp_id, col, src, direction, weight in components:
            contribution_rows.append({
                "snapshot_id": snap_id,
                "component_id": comp_id,
                "raw_value": raw_by_component[comp_id].get(sc),
                "percentile_score": round(pct_by_scheme[sc][comp_id], 2),
                "contribution": round(pct_by_scheme[sc][comp_id] * float(weight), 4),
            })

    if contribution_rows:
        db.execute(text("""
            INSERT INTO selfmade_ranking_contribution
                (snapshot_id, component_id, raw_value, percentile_score, contribution)
            VALUES (:snapshot_id, :component_id, :raw_value, :percentile_score, :contribution)
            ON CONFLICT (snapshot_id, component_id) DO UPDATE SET
                raw_value = EXCLUDED.raw_value,
                percentile_score = EXCLUDED.percentile_score,
                contribution = EXCLUDED.contribution
        """), contribution_rows)

    db.commit()

    return {
        "status": "ok",
        "rule_version_id": resolved_rv,
        "evaluation_date": str(evaluation_date),
        "funds_scored": len(scored_schemecodes),
        "funds_skipped_insufficient_data": len(schemecodes) - len(scored_schemecodes),
        "categories_scored": len({bucket_by_scheme[sc] for sc in scored_schemecodes}),
    }
