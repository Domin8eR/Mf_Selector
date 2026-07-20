"""
Bootstrap script — Category Rankings rule engine tables + default v1.0
rule version, then a real recompute for today.

Creates (idempotent, safe to rerun):
  selfmade_rule_set, selfmade_rule_version, selfmade_rule_component
  selfmade_ranking_contribution
  Adds: rank_delta_6m, information_ratio_3yr, composite_score_v2 columns
  to selfmade_ranking_snapshot; ir_slope_6m_proxy to selfmade_scheme_metrics.
  Seeds the default v1.0 rule version + components if none exists yet.

As of the governance-gap fix (see app/rankings/recompute.py's docstring),
this script no longer computes composite scores itself — it delegates to
recompute_all_rankings(), the one canonical, governed implementation. This
also means it no longer fabricates 6 months of synthetic historical
snapshots with random drift/noise (the old EVAL_DATES / drift_factor_for_fund
/ synth_value_at machinery, removed) — that was fake data being presented
as real 6-month trend. Real trend now accumulates naturally: each time
this script (or a rule approval) runs, it adds ONE real data point for
today under category_taxonomy_current's real bucket_36 categories, across
the full ranked universe rather than only Large/Mid/Small Cap.

Known side effect, out of scope for this fix: ir_slope_6m_proxy was
computed from that fake synthetic history (a linear-regression slope over
6 fabricated monthly IR values). Removing the fabrication means this
column is no longer updated here — it stays frozen at its last computed
value (an inert historical artifact, same treatment as the retired
selfmade_scheme_ranking table) until a real multi-date IR history exists
to compute a real slope from. Flagged, not fixed, in this pass.

Run: python scripts/seed_category_rankings.py
"""

import os
import sys
import psycopg2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from app.core.db import SessionLocal  # noqa: E402
from app.rankings.recompute import recompute_all_rankings  # noqa: E402

DSN = os.environ.get(
    "DATABASE_URL",
    "postgresql://piyushrajlenka:29062002@localhost:5432/Altstreet_AI",
)


def run():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()

    # ── 1. Extend selfmade_ranking_snapshot with new columns ─────────────────
    print("→ Extending selfmade_ranking_snapshot ...")
    for col, defn in [
        ("rank_delta_6m",         "SMALLINT"),
        ("information_ratio_3yr", "NUMERIC(10,6)"),
        ("composite_score_v2",    "NUMERIC(10,4)"),   # rule-engine score, replaces ad-hoc
    ]:
        cur.execute(f"""
            ALTER TABLE selfmade_ranking_snapshot
            ADD COLUMN IF NOT EXISTS {col} {defn};
        """)

    # ── 2. Extend selfmade_scheme_metrics with ir_slope_6m_proxy ─────────────
    print("→ Extending selfmade_scheme_metrics ...")
    cur.execute("""
        ALTER TABLE selfmade_scheme_metrics
        ADD COLUMN IF NOT EXISTS ir_slope_6m_proxy NUMERIC(12,8);
    """)

    conn.commit()

    # ── 3. Create rule engine tables ──────────────────────────────────────────
    print("→ Creating rule engine tables ...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS selfmade_rule_set (
            id          SERIAL PRIMARY KEY,
            name        VARCHAR(200) NOT NULL,
            description TEXT,
            is_active   BOOLEAN DEFAULT TRUE,
            created_at  TIMESTAMP DEFAULT NOW()
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS selfmade_rule_version (
            id           SERIAL PRIMARY KEY,
            rule_set_id  INTEGER NOT NULL REFERENCES selfmade_rule_set(id),
            version_label VARCHAR(50) NOT NULL,
            is_active    BOOLEAN DEFAULT TRUE,
            approved_by  VARCHAR(200),
            approved_at  TIMESTAMP,
            change_note  TEXT,
            created_at   TIMESTAMP DEFAULT NOW()
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS selfmade_rule_component (
            id              SERIAL PRIMARY KEY,
            rule_version_id INTEGER NOT NULL REFERENCES selfmade_rule_version(id),
            component_name  VARCHAR(200) NOT NULL,
            metric_column   VARCHAR(100) NOT NULL,
            metric_source   VARCHAR(100) NOT NULL,
            direction       VARCHAR(20)  NOT NULL CHECK (direction IN ('higher_better','lower_better')),
            weight          NUMERIC(5,4) NOT NULL,
            label_display   VARCHAR(200),
            data_note       TEXT,
            sort_order      SMALLINT DEFAULT 0,
            created_at      TIMESTAMP DEFAULT NOW()
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS selfmade_ranking_contribution (
            id                BIGSERIAL PRIMARY KEY,
            snapshot_id       BIGINT  NOT NULL REFERENCES selfmade_ranking_snapshot(id),
            component_id      INTEGER NOT NULL REFERENCES selfmade_rule_component(id),
            raw_value         NUMERIC(12,6),
            percentile_score  NUMERIC(6,2),
            contribution      NUMERIC(8,4),
            UNIQUE (snapshot_id, component_id)
        );
    """)
    conn.commit()

    # ── 4. Seed rule set + version + components ───────────────────────────────
    # Bootstrap ONLY if no rule version exists yet. This used to
    # unconditionally DELETE + re-insert v1.0 on every run, which would
    # have wiped any real approved versions from Rule Approval the moment
    # this script became part of a repeatable (daily) pipeline in Step 5 —
    # a genuine violation of the "rule versions are append-only immutable
    # history" rule. Now it's a true one-time bootstrap.
    cur.execute("SELECT COUNT(*) FROM selfmade_rule_version;")
    if cur.fetchone()[0] > 0:
        print("→ Rule set / version / components already exist — skipping bootstrap seed.")
        conn.commit()
        cur.close()
        conn.close()
        return _recompute_today()

    print("→ Seeding rule set / version / components (first-time bootstrap) ...")

    cur.execute("""
        INSERT INTO selfmade_rule_set (name, description, is_active)
        VALUES ('Client Default Rules',
                'Default weighted scoring rule set for ranked fund research.', TRUE)
        RETURNING id;
    """)
    rs_id = cur.fetchone()[0]

    cur.execute("""
        INSERT INTO selfmade_rule_version
            (rule_set_id, version_label, is_active, approved_by, approved_at, change_note)
        VALUES (%s, 'v1.0', TRUE, 'system', NOW(),
                'Initial rule version — 4 components, weights sum to 1.0')
        RETURNING id;
    """, (rs_id,))
    rv_id = cur.fetchone()[0]

    components_def = [
        # (name, column, source, direction, weight, display, note, sort)
        (
            "3Y Information Ratio",
            "information_ratio_3yr",
            "selfmade_scheme_metrics",
            "higher_better",
            "0.4000",
            "IR₃ (Information Ratio — 3Y)",
            None,
            1,
        ),
        (
            "3Y Sharpe Ratio",
            "sharpe_ratio_3yr",
            "selfmade_scheme_metrics",
            "higher_better",
            "0.2500",
            "Sharpe₃ (Sharpe Ratio — 3Y)",
            "Proxy for 2Y IR Slope trend: no IR time-series available in source data.",
            2,
        ),
        (
            "Active Return 3Y",
            "active_3yr_ret",
            "selfmade_scheme_returns",
            "higher_better",
            "0.2000",
            "Active Ret₃ (Fund − Benchmark CAGR, 3Y)",
            "Proxy for Outperformance Ratio: outperformed_3yr is boolean; "
            "active_3yr_ret gives continuous outperformance magnitude.",
            3,
        ),
        (
            "Tracking Error 3Y",
            "tracking_error_3yr",
            "selfmade_scheme_metrics",
            "lower_better",
            "0.1500",
            "TE₃ (Tracking Error — 3Y, lower = better)",
            "Proxy for Downside Capture 3Y: dedicated downside-capture data unavailable.",
            4,
        ),
    ]

    component_ids = {}
    for (cname, col, src, direction, wt, display, note, sort) in components_def:
        cur.execute("""
            INSERT INTO selfmade_rule_component
                (rule_version_id, component_name, metric_column, metric_source,
                 direction, weight, label_display, data_note, sort_order)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id;
        """, (rv_id, cname, col, src, direction, wt, display, note, sort))
        cid = cur.fetchone()[0]
        component_ids[col] = cid

    conn.commit()
    cur.close()
    conn.close()
    _recompute_today()


def _recompute_today():
    """
    The real, governed recompute — replaces the old steps 5-9 (synthetic
    6-month snapshot generation + hardcoded formula). Scores today's date
    against the currently active rule version, across every real bucket_36
    category, and prints the same kind of summary the old verification
    step did.
    """
    print("→ Recomputing rankings via the governed pipeline (recompute_all_rankings) ...")
    db = SessionLocal()
    try:
        result = recompute_all_rankings(db)
        print(f"   {result}")
    finally:
        db.close()


if __name__ == "__main__":
    run()
