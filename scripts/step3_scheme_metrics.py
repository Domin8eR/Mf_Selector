"""
Step 3: Create and populate selfmade_scheme_metrics.

Computes risk-adjusted metrics from selfmade_scheme_returns and
mf_ratios_defaultbm. Information ratio uses the proxy formula since
mf_ratios_defaultbm.informationratio is NULL for all rows.

Idempotent — drops and recreates the table on every run.
"""

import math
import os

import psycopg2
from psycopg2.extras import execute_values

DB_HOST = os.environ.get("DB_HOST", os.environ.get("POSTGRES_HOST", "localhost"))
DB_PORT = os.environ.get("DB_PORT", os.environ.get("POSTGRES_PORT", "5432"))
DB_NAME = os.environ.get("DB_NAME", os.environ.get("POSTGRES_DB", "Altstreet_AI"))
DB_USER = os.environ.get("DB_USER", os.environ.get("POSTGRES_USER", "piyushrajlenka"))
DB_PASSWORD = os.environ.get("DB_PASSWORD", os.environ.get("POSTGRES_PASSWORD", ""))

RISK_FREE_3YR = 0.195  # 6.5% × 3


def clamp(val, lo, hi):
    if val is None:
        return None
    return max(lo, min(hi, val))


def main():
    conn = psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASSWORD,
    )
    conn.autocommit = False
    cur = conn.cursor()

    print("Step 3: Creating selfmade_scheme_metrics ...")

    cur.execute("DROP TABLE IF EXISTS selfmade_scheme_metrics CASCADE;")
    cur.execute("""
        CREATE TABLE selfmade_scheme_metrics (
            schemecode INTEGER UNIQUE NOT NULL,
            category VARCHAR(200),
            benchmark_index VARCHAR(300),
            as_of_date DATE,
            information_ratio_3yr NUMERIC(10,6),
            jensens_alpha_3yr NUMERIC(10,6),
            sharpe_ratio_3yr NUMERIC(10,6),
            sortino_ratio_3yr NUMERIC(10,6),
            tracking_error_3yr NUMERIC(10,6),
            outperformed_1yr BOOLEAN,
            outperformed_3yr BOOLEAN,
            outperformed_5yr BOOLEAN,
            is_fallback_benchmark BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    # Fetch returns + Accord ratios in one join
    cur.execute("""
        SELECT sr.schemecode, sr.category, sr.benchmark_index, sr.as_of_date,
               sr.fund_1yr_ret, sr.fund_3yr_ret, sr.fund_5yr_ret,
               sr.bm_1yr_ret, sr.bm_3yr_ret, sr.bm_5yr_ret,
               sr.active_1yr_ret, sr.active_3yr_ret, sr.active_5yr_ret,
               sr.is_fallback_benchmark,
               rat.sharpe as accord_sharpe,
               rat.sortino as accord_sortino,
               rat.beta as accord_beta
        FROM selfmade_scheme_returns sr
        LEFT JOIN mf_ratios_defaultbm rat
            ON rat.schemecode = sr.schemecode AND rat.flag = 'A'
        ORDER BY sr.schemecode;
    """)
    rows = cur.fetchall()
    print(f"  Fetched {len(rows)} schemes")

    inserts = []
    for i, row in enumerate(rows):
        sc = row[0]
        cat, bm_idx, as_of = row[1], row[2], row[3]
        f1 = float(row[4]) if row[4] is not None else None
        f3 = float(row[5]) if row[5] is not None else None
        f5 = float(row[6]) if row[6] is not None else None
        bm1 = float(row[7]) if row[7] is not None else None
        bm3 = float(row[8]) if row[8] is not None else None
        bm5 = float(row[9]) if row[9] is not None else None
        a1 = float(row[10]) if row[10] is not None else None
        a3 = float(row[11]) if row[11] is not None else None
        a5 = float(row[12]) if row[12] is not None else None
        is_fb = row[13]
        accord_sharpe = float(row[14]) if row[14] is not None else None
        accord_sortino = float(row[15]) if row[15] is not None else None
        accord_beta = float(row[16]) if row[16] is not None else None

        # --- Tracking error proxy ---
        te = None
        if a3 is not None and a1 is not None:
            te = abs(a3 - a1) + 0.001

        # --- Information ratio ---
        ir = None
        if a3 is not None and te is not None and te != 0:
            ir = clamp(a3 / te, -10, 10)

        # --- Jensen's alpha ---
        alpha = None
        beta = accord_beta if accord_beta is not None else 1.0
        if f3 is not None and bm3 is not None:
            alpha = f3 - (RISK_FREE_3YR + beta * (bm3 - RISK_FREE_3YR))

        # --- Sharpe ratio ---
        sharpe = None
        if accord_sharpe is not None:
            sharpe = clamp(accord_sharpe, -20, 20)
        elif f3 is not None and f1 is not None:
            vol_proxy = abs(f3 - f1) * math.sqrt(3) + 0.001
            sharpe = clamp((f3 - RISK_FREE_3YR) / vol_proxy, -20, 20)

        # --- Sortino ratio ---
        sortino = None
        if accord_sortino is not None:
            sortino = accord_sortino

        # --- Outperformance flags ---
        op1 = (f1 > bm1) if (f1 is not None and bm1 is not None) else None
        op3 = (f3 > bm3) if (f3 is not None and bm3 is not None) else None
        op5 = (f5 > bm5) if (f5 is not None and bm5 is not None) else None

        inserts.append((
            sc, cat, bm_idx, as_of,
            ir, alpha, sharpe, sortino, te,
            op1, op3, op5, is_fb,
        ))

        if (i + 1) % 500 == 0:
            print(f"  Processed {i + 1}/{len(rows)} schemes ...")

    print(f"  Prepared {len(inserts)} rows for insert")

    if inserts:
        execute_values(
            cur,
            """INSERT INTO selfmade_scheme_metrics
               (schemecode, category, benchmark_index, as_of_date,
                information_ratio_3yr, jensens_alpha_3yr,
                sharpe_ratio_3yr, sortino_ratio_3yr, tracking_error_3yr,
                outperformed_1yr, outperformed_3yr, outperformed_5yr,
                is_fallback_benchmark)
               VALUES %s
               ON CONFLICT (schemecode) DO UPDATE SET
                 category = EXCLUDED.category,
                 benchmark_index = EXCLUDED.benchmark_index,
                 as_of_date = EXCLUDED.as_of_date,
                 information_ratio_3yr = EXCLUDED.information_ratio_3yr,
                 jensens_alpha_3yr = EXCLUDED.jensens_alpha_3yr,
                 sharpe_ratio_3yr = EXCLUDED.sharpe_ratio_3yr,
                 sortino_ratio_3yr = EXCLUDED.sortino_ratio_3yr,
                 tracking_error_3yr = EXCLUDED.tracking_error_3yr,
                 outperformed_1yr = EXCLUDED.outperformed_1yr,
                 outperformed_3yr = EXCLUDED.outperformed_3yr,
                 outperformed_5yr = EXCLUDED.outperformed_5yr,
                 is_fallback_benchmark = EXCLUDED.is_fallback_benchmark""",
            inserts,
            page_size=1000,
        )

    conn.commit()

    cur.execute("""
        SELECT COUNT(*) as total,
               COUNT(information_ratio_3yr) as has_ir,
               COUNT(jensens_alpha_3yr) as has_alpha,
               COUNT(sharpe_ratio_3yr) as has_sharpe,
               COUNT(sortino_ratio_3yr) as has_sortino,
               COUNT(tracking_error_3yr) as has_te
        FROM selfmade_scheme_metrics;
    """)
    r = cur.fetchone()
    print(f"\n  Summary:")
    print(f"    Total rows:        {r[0]}")
    print(f"    With IR:           {r[1]}")
    print(f"    With Alpha:        {r[2]}")
    print(f"    With Sharpe:       {r[3]}")
    print(f"    With Sortino:      {r[4]}")
    print(f"    With Tracking Err: {r[5]}")

    cur.close()
    conn.close()
    print("Step 3 complete.\n")


if __name__ == "__main__":
    main()
