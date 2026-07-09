"""
Seed script — Category Rankings rule engine + 6 monthly snapshots.

Creates:
  selfmade_rule_set, selfmade_rule_version, selfmade_rule_component
  selfmade_ranking_contribution
  Adds: rank_delta_6m, information_ratio_3yr to selfmade_ranking_snapshot
  Adds: ir_slope_6m_proxy to selfmade_scheme_metrics
  Seeds 6 monthly snapshots: 2026-02-09 → 2026-07-09
  Scores each snapshot using percentile normalization (0-100, direction-aware)
  Weighted sum composite_score = Σ(percentile_score × weight)

Run: python scripts/seed_category_rankings.py
"""

import os, sys, math, random
from datetime import date, datetime
from decimal import Decimal
import psycopg2
from psycopg2.extras import execute_values

DSN = os.environ.get(
    "DATABASE_URL",
    "postgresql://piyushrajlenka:29062002@localhost:5432/Altstreet_AI",
)

# ── Status label cutoffs (configurable) ──────────────────────────────────────
STATUS_CUTOFFS = {
    "Strong":  0.85,   # top 15 %
    "Good":    0.50,   # next 35 %
    "Neutral": 0.15,   # next 35 %
    # below 15th percentile → "Weak"
}

# ── Evaluation dates (oldest → newest) ───────────────────────────────────────
EVAL_DATES = [
    date(2026, 2,  9),
    date(2026, 3,  9),
    date(2026, 4,  9),
    date(2026, 5,  9),
    date(2026, 6,  9),
    date(2026, 7,  9),
]

CATEGORIES = ["Equity — Large Cap", "Equity — Mid Cap", "Equity — Small Cap"]

random.seed(42)


def status_label(rank: int, total: int) -> str:
    """Map rank → status label using configurable cutoffs."""
    percentile = 1.0 - (rank - 1) / total  # rank 1 = 100th pct
    if percentile >= STATUS_CUTOFFS["Strong"]:
        return "Strong"
    if percentile >= STATUS_CUTOFFS["Good"]:
        return "Good"
    if percentile >= STATUS_CUTOFFS["Neutral"]:
        return "Neutral"
    return "Weak"


def percentile_rank(value: float, all_values: list[float], higher_better: bool) -> float:
    """
    Return a 0-100 percentile score for value within all_values.
    higher_better=True  → higher raw value = higher score
    higher_better=False → lower raw value = higher score (inverted)
    """
    if not all_values:
        return 50.0
    sorted_vals = sorted(all_values)
    n = len(sorted_vals)
    # count how many values are strictly below
    below = sum(1 for v in sorted_vals if v < value)
    pct = below / n * 100.0
    if not higher_better:
        pct = 100.0 - pct
    return round(pct, 2)


def linear_slope(ys: list[float]) -> float:
    """Slope of linear regression through evenly-spaced y values (x = 0..n-1)."""
    n = len(ys)
    if n < 2:
        return 0.0
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n))
    den = sum((xs[i] - mean_x) ** 2 for i in range(n))
    return num / den if den else 0.0


def drift_factor_for_fund(ir_current: float, ir_all: list[float]) -> float:
    """
    Funds in top 25 % get a mild positive drift (were lower before → trend up).
    Funds in bottom 25 % get a mild negative drift (were higher before → trend down).
    Others: small noise.
    Returns per-month drift multiplier applied to months_back.
    """
    sorted_ir = sorted(ir_all)
    n = len(sorted_ir)
    rank = sum(1 for v in sorted_ir if v < ir_current)
    pct = rank / n
    if pct >= 0.75:
        return -0.018   # top quartile: trending upward
    if pct <= 0.25:
        return +0.012   # bottom quartile: trending downward
    return random.uniform(-0.005, 0.005)


def synth_value_at(current: float, drift_per_month: float, months_back: int) -> float:
    """Synthetic value n months before current, given drift."""
    v = current - drift_per_month * months_back
    noise = random.gauss(0, abs(current) * 0.02 + 0.001)
    return v + noise


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
    print("→ Seeding rule set / version / components ...")

    # Idempotent: delete & re-insert
    cur.execute("DELETE FROM selfmade_ranking_contribution;")
    cur.execute("DELETE FROM selfmade_rule_component;")
    cur.execute("DELETE FROM selfmade_rule_version;")
    cur.execute("DELETE FROM selfmade_rule_set;")

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

    # ── 5. Load base metrics for every fund ───────────────────────────────────
    print("→ Loading base metrics ...")
    cur.execute("""
        SELECT
            sm.schemecode,
            sm.category,
            sm.information_ratio_3yr,
            sm.sharpe_ratio_3yr,
            sm.tracking_error_3yr,
            sr.active_3yr_ret,
            srs.fund_name
        FROM selfmade_scheme_metrics sm
        LEFT JOIN selfmade_scheme_returns sr
            ON sr.schemecode = sm.schemecode
        LEFT JOIN selfmade_ranking_snapshot srs
            ON srs.schemecode = sm.schemecode
            AND srs.snapshot_date = (
                SELECT MAX(snapshot_date) FROM selfmade_ranking_snapshot
            )
        WHERE sm.category IN ('Equity — Large Cap',
                              'Equity — Mid Cap',
                              'Equity — Small Cap')
          AND sm.information_ratio_3yr IS NOT NULL
    """)
    fund_rows = cur.fetchall()

    # Organise by category
    # funds[category] = list of dicts
    funds_by_cat: dict[str, list[dict]] = {}
    for row in fund_rows:
        schemecode, cat, ir3, sharpe3, te3, active_ret3, fund_name = row
        if cat not in funds_by_cat:
            funds_by_cat[cat] = []
        funds_by_cat[cat].append({
            "schemecode":   schemecode,
            "category":     cat,
            "ir3":          float(ir3)         if ir3         is not None else None,
            "sharpe3":      float(sharpe3)      if sharpe3     is not None else None,
            "te3":          float(te3)          if te3         is not None else None,
            "active_ret3":  float(active_ret3)  if active_ret3 is not None else None,
            "fund_name":    fund_name or f"Fund-{schemecode}",
        })

    print(f"   Loaded {sum(len(v) for v in funds_by_cat.values())} funds "
          f"across {len(funds_by_cat)} categories")

    # ── 6. Build 6 monthly snapshots ──────────────────────────────────────────
    # For each category, compute drift factors per fund (based on IR rank),
    # then synthesize metric values at each historical date.

    # Dict: schemecode → list of (date, ir3_value) for slope computation later
    ir_history: dict[int, list[float]] = {}

    for cat, funds in funds_by_cat.items():
        print(f"   Seeding {cat} ...")

        ir_all = [f["ir3"] for f in funds if f["ir3"] is not None]

        # Compute per-fund drift factors
        for f in funds:
            if f["ir3"] is not None:
                f["ir_drift"]     = drift_factor_for_fund(f["ir3"], ir_all)
                f["sharpe_drift"] = f["ir_drift"] * 0.8
                # TE inverse: top-IR funds trend to lower TE (better), bottom → higher TE
                f["te_drift"]     = -f["ir_drift"] * 0.6
                f["ar_drift"]     = f["ir_drift"] * 0.5
            else:
                f["ir_drift"] = f["sharpe_drift"] = f["te_drift"] = f["ar_drift"] = 0.0

        latest_date = EVAL_DATES[-1]  # 2026-07-09

        for eval_date in EVAL_DATES:
            months_back = (latest_date.year - eval_date.year) * 12 + \
                          (latest_date.month - eval_date.month)

            # Build metric vectors for this date (with synthetic drift)
            for f in funds:
                if months_back == 0:
                    f["ir3_at"]       = f["ir3"]
                    f["sharpe3_at"]   = f["sharpe3"]
                    f["te3_at"]       = f["te3"]
                    f["active_ret3_at"] = f["active_ret3"]
                else:
                    ir3 = f["ir3"]
                    if ir3 is not None:
                        f["ir3_at"] = synth_value_at(
                            ir3, f["ir_drift"], months_back
                        )
                    else:
                        f["ir3_at"] = None

                    s3 = f["sharpe3"]
                    if s3 is not None:
                        f["sharpe3_at"] = synth_value_at(
                            s3, f["sharpe_drift"], months_back
                        )
                    else:
                        f["sharpe3_at"] = None

                    te = f["te3"]
                    if te is not None:
                        raw = synth_value_at(te, f["te_drift"], months_back)
                        f["te3_at"] = max(0.0005, raw)
                    else:
                        f["te3_at"] = None

                    ar = f["active_ret3"]
                    if ar is not None:
                        f["active_ret3_at"] = synth_value_at(
                            ar, f["ar_drift"], months_back
                        )
                    else:
                        f["active_ret3_at"] = None

            # Build within-category percentile vectors for each component
            ir3_vals    = [f["ir3_at"]        for f in funds if f["ir3_at"]         is not None]
            sharpe_vals = [f["sharpe3_at"]     for f in funds if f["sharpe3_at"]     is not None]
            te_vals     = [f["te3_at"]         for f in funds if f["te3_at"]         is not None]
            ar_vals     = [f["active_ret3_at"] for f in funds if f["active_ret3_at"] is not None]

            # Compute composite score per fund
            for f in funds:
                pct_ir    = percentile_rank(f["ir3_at"],        ir3_vals,    True)  if f["ir3_at"]        is not None else 50.0
                pct_sh    = percentile_rank(f["sharpe3_at"],    sharpe_vals, True)  if f["sharpe3_at"]    is not None else 50.0
                pct_ar    = percentile_rank(f["active_ret3_at"],ar_vals,     True)  if f["active_ret3_at"]is not None else 50.0
                pct_te    = percentile_rank(f["te3_at"],        te_vals,     False) if f["te3_at"]        is not None else 50.0

                f["pct_ir"]  = pct_ir
                f["pct_sh"]  = pct_sh
                f["pct_ar"]  = pct_ar
                f["pct_te"]  = pct_te
                f["comp_score"] = (
                    pct_ir * 0.40 +
                    pct_sh * 0.25 +
                    pct_ar * 0.20 +
                    pct_te * 0.15
                )

            # Sort by composite score DESC → assign ranks
            funds_sorted = sorted(funds, key=lambda x: x["comp_score"], reverse=True)
            n_total = len(funds_sorted)

            snap_rows = []
            for rank_1idx, f in enumerate(funds_sorted, start=1):
                snap_rows.append((
                    eval_date,
                    cat,
                    f["schemecode"],
                    f["fund_name"],
                    rank_1idx,
                    round(f["comp_score"], 4),
                    round(f["sharpe3_at"], 4) if f["sharpe3_at"] is not None else None,
                    "RULE_ENGINE_V1",
                    round(f["ir3_at"], 6) if f["ir3_at"] is not None else None,
                    round(f["comp_score"], 4),  # composite_score_v2
                ))
                # Track IR history for slope computation
                if f["schemecode"] not in ir_history:
                    ir_history[f["schemecode"]] = []
                ir_history[f["schemecode"]].append(
                    f["ir3_at"] if f["ir3_at"] is not None else f.get("ir3", 0.0) or 0.0
                )

            # Upsert into selfmade_ranking_snapshot
            cur.execute("""
                DELETE FROM selfmade_ranking_contribution
                WHERE snapshot_id IN (
                    SELECT id FROM selfmade_ranking_snapshot
                    WHERE snapshot_date = %s AND category = %s
                )
            """, (eval_date, cat))

            cur.execute("""
                DELETE FROM selfmade_ranking_snapshot
                WHERE snapshot_date = %s AND category = %s
            """, (eval_date, cat))

            execute_values(cur, """
                INSERT INTO selfmade_ranking_snapshot
                    (snapshot_date, category, schemecode, fund_name,
                     rank_in_category, composite_score, sharpe_score,
                     sort_basis, information_ratio_3yr, composite_score_v2)
                VALUES %s
            """, snap_rows)

            # Retrieve inserted IDs for contributions
            cur.execute("""
                SELECT id, schemecode FROM selfmade_ranking_snapshot
                WHERE snapshot_date = %s AND category = %s
            """, (eval_date, cat))
            snap_id_map = {row[1]: row[0] for row in cur.fetchall()}

            # Store contributions per fund per component
            contrib_rows = []
            comp_id_ir = component_ids["information_ratio_3yr"]
            comp_id_sh = component_ids["sharpe_ratio_3yr"]
            comp_id_ar = component_ids["active_3yr_ret"]
            comp_id_te = component_ids["tracking_error_3yr"]

            for f in funds:
                snap_id = snap_id_map.get(f["schemecode"])
                if snap_id is None:
                    continue
                contrib_rows.extend([
                    (snap_id, comp_id_ir,
                     round(f["ir3_at"], 6)        if f["ir3_at"] is not None else None,
                     f["pct_ir"], round(f["pct_ir"] * 0.40, 4)),
                    (snap_id, comp_id_sh,
                     round(f["sharpe3_at"], 6)    if f["sharpe3_at"] is not None else None,
                     f["pct_sh"], round(f["pct_sh"] * 0.25, 4)),
                    (snap_id, comp_id_ar,
                     round(f["active_ret3_at"], 6)if f["active_ret3_at"] is not None else None,
                     f["pct_ar"], round(f["pct_ar"] * 0.20, 4)),
                    (snap_id, comp_id_te,
                     round(f["te3_at"], 6)        if f["te3_at"] is not None else None,
                     f["pct_te"], round(f["pct_te"] * 0.15, 4)),
                ])

            execute_values(cur, """
                INSERT INTO selfmade_ranking_contribution
                    (snapshot_id, component_id, raw_value, percentile_score, contribution)
                VALUES %s
                ON CONFLICT (snapshot_id, component_id) DO UPDATE
                    SET raw_value = EXCLUDED.raw_value,
                        percentile_score = EXCLUDED.percentile_score,
                        contribution = EXCLUDED.contribution
            """, contrib_rows)

            print(f"   ✓ {cat} / {eval_date} → {n_total} funds")
        conn.commit()

    # ── 7. Compute ir_slope_6m_proxy for each fund ────────────────────────────
    print("→ Computing ir_slope_6m_proxy ...")
    update_slope_rows = []
    for schemecode, ir_vals in ir_history.items():
        if len(ir_vals) >= 2:
            slope = linear_slope(ir_vals)
            update_slope_rows.append((round(slope, 8), schemecode))

    cur.executemany("""
        UPDATE selfmade_scheme_metrics
        SET ir_slope_6m_proxy = %s
        WHERE schemecode = %s
    """, update_slope_rows)

    # ── 8. Compute rank_delta_6m ──────────────────────────────────────────────
    print("→ Computing rank_delta_6m ...")
    oldest_date = EVAL_DATES[0]   # 2026-02-09
    latest_date = EVAL_DATES[-1]  # 2026-07-09

    cur.execute("""
        UPDATE selfmade_ranking_snapshot AS s_new
        SET rank_delta_6m = s_new.rank_in_category - s_old.rank_in_category
        FROM selfmade_ranking_snapshot s_old
        WHERE s_new.snapshot_date = %s
          AND s_old.snapshot_date = %s
          AND s_new.schemecode = s_old.schemecode
          AND s_new.category = s_old.category
    """, (latest_date, oldest_date))

    conn.commit()

    # ── 9. Also recompute rank_delta (week-over-week) for the Jul snapshot ────
    prev_date = date(2026, 7, 2)   # the other pre-existing snapshot
    cur.execute("""
        SELECT COUNT(*) FROM selfmade_ranking_snapshot
        WHERE snapshot_date = %s
    """, (prev_date,))
    if cur.fetchone()[0] > 0:
        cur.execute("""
            UPDATE selfmade_scheme_ranking sr
            SET rank_delta = s_new.rank_in_category - s_old.rank_in_category,
                rank_in_category_prev = s_old.rank_in_category
            FROM selfmade_ranking_snapshot s_new
            JOIN selfmade_ranking_snapshot s_old
                ON s_old.schemecode = s_new.schemecode
               AND s_old.category   = s_new.category
               AND s_old.snapshot_date = %s
            WHERE s_new.snapshot_date = %s
              AND sr.schemecode = s_new.schemecode
        """, (prev_date, latest_date))
        conn.commit()

    print("→ Verifying ...")
    cur.execute("""
        SELECT snapshot_date, category, COUNT(*) AS n,
               ROUND(AVG(composite_score_v2), 2) AS avg_score
        FROM selfmade_ranking_snapshot
        WHERE snapshot_date = ANY(%s::date[])
        GROUP BY snapshot_date, category
        ORDER BY snapshot_date, category
    """, ([d.isoformat() for d in EVAL_DATES],))
    for row in cur.fetchall():
        print(f"   {row[0]}  {row[1]:<26}  n={row[2]}  avg_score={row[3]}")

    cur.execute("SELECT COUNT(*) FROM selfmade_ranking_contribution;")
    print(f"\n   selfmade_ranking_contribution rows: {cur.fetchone()[0]}")

    cur.execute("SELECT COUNT(*) FROM selfmade_scheme_metrics WHERE ir_slope_6m_proxy IS NOT NULL;")
    print(f"   Funds with ir_slope_6m_proxy:       {cur.fetchone()[0]}")

    cur.execute("""
        SELECT COUNT(*) FROM selfmade_ranking_snapshot
        WHERE snapshot_date = %s AND rank_delta_6m IS NOT NULL
    """, (latest_date,))
    print(f"   Funds with rank_delta_6m:            {cur.fetchone()[0]}")

    cur.close()
    conn.close()
    print("\nDone — category rankings seeded.")


if __name__ == "__main__":
    run()
