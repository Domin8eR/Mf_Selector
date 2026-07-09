"""
Step 4: Create and populate selfmade_scheme_ranking.

Computes percentile ranks within each category, composite scores,
and overall category rank.  Only includes schemes with 3yr returns.

Idempotent — drops and recreates the table on every run.
"""

import os

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

DB_HOST = os.environ.get("DB_HOST", os.environ.get("POSTGRES_HOST", "localhost"))
DB_PORT = os.environ.get("DB_PORT", os.environ.get("POSTGRES_PORT", "5432"))
DB_NAME = os.environ.get("DB_NAME", os.environ.get("POSTGRES_DB", "Altstreet_AI"))
DB_USER = os.environ.get("DB_USER", os.environ.get("POSTGRES_USER", "piyushrajlenka"))
DB_PASSWORD = os.environ.get("DB_PASSWORD", os.environ.get("POSTGRES_PASSWORD", ""))


def main():
    conn = psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASSWORD,
    )
    conn.autocommit = False
    cur = conn.cursor()

    print("Step 4: Creating selfmade_scheme_ranking ...")

    cur.execute("DROP TABLE IF EXISTS selfmade_scheme_ranking CASCADE;")
    cur.execute("""
        CREATE TABLE selfmade_scheme_ranking (
            schemecode INTEGER UNIQUE NOT NULL,
            amfi_name VARCHAR(500),
            category VARCHAR(200),
            benchmark_index VARCHAR(300),
            fund_1yr_ret NUMERIC(12,6),
            fund_3yr_ret NUMERIC(12,6),
            fund_5yr_ret NUMERIC(12,6),
            active_3yr_ret NUMERIC(12,6),
            information_ratio_3yr NUMERIC(10,6),
            jensens_alpha_3yr NUMERIC(10,6),
            sharpe_ratio_3yr NUMERIC(10,6),
            pct_1yr_ret NUMERIC(6,2),
            pct_3yr_ret NUMERIC(6,2),
            pct_5yr_ret NUMERIC(6,2),
            pct_ir_3yr NUMERIC(6,2),
            pct_sharpe_3yr NUMERIC(6,2),
            composite_score NUMERIC(8,4),
            rank_in_category INTEGER,
            total_in_category INTEGER,
            rank_in_category_prev INTEGER,
            rank_delta INTEGER,
            is_fallback_benchmark BOOLEAN DEFAULT FALSE,
            as_of_date DATE,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    cur.execute("""
        SELECT sr.schemecode, cb.amfi_name, sr.category, sr.benchmark_index,
               sr.fund_1yr_ret, sr.fund_3yr_ret, sr.fund_5yr_ret,
               sr.active_3yr_ret,
               sm.information_ratio_3yr, sm.jensens_alpha_3yr, sm.sharpe_ratio_3yr,
               sr.is_fallback_benchmark, sr.as_of_date
        FROM selfmade_scheme_returns sr
        JOIN selfmade_scheme_category_benchmark cb USING (schemecode)
        JOIN selfmade_scheme_metrics sm USING (schemecode)
        WHERE sr.fund_3yr_ret IS NOT NULL
        ORDER BY sr.schemecode;
    """)
    rows = cur.fetchall()
    print(f"  Fetched {len(rows)} schemes with 3yr returns")

    df = pd.DataFrame(rows, columns=[
        "schemecode", "amfi_name", "category", "benchmark_index",
        "fund_1yr_ret", "fund_3yr_ret", "fund_5yr_ret",
        "active_3yr_ret",
        "information_ratio_3yr", "jensens_alpha_3yr", "sharpe_ratio_3yr",
        "is_fallback_benchmark", "as_of_date",
    ])

    for col in ["fund_1yr_ret", "fund_3yr_ret", "fund_5yr_ret",
                "active_3yr_ret", "information_ratio_3yr",
                "jensens_alpha_3yr", "sharpe_ratio_3yr"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Percentile ranks within category
    for col, pct_col in [
        ("fund_1yr_ret", "pct_1yr_ret"),
        ("fund_3yr_ret", "pct_3yr_ret"),
        ("fund_5yr_ret", "pct_5yr_ret"),
        ("information_ratio_3yr", "pct_ir_3yr"),
        ("sharpe_ratio_3yr", "pct_sharpe_3yr"),
    ]:
        df[pct_col] = df.groupby("category")[col].transform(
            lambda x: x.rank(pct=True, na_option="keep") * 100
        )

    # fund_5yr_ret NULL → assign 50th percentile
    df["pct_5yr_ret"] = df["pct_5yr_ret"].fillna(50.0)

    # Fill NaN percentiles for IR and Sharpe with 50 (neutral)
    df["pct_ir_3yr"] = df["pct_ir_3yr"].fillna(50.0)
    df["pct_sharpe_3yr"] = df["pct_sharpe_3yr"].fillna(50.0)
    df["pct_1yr_ret"] = df["pct_1yr_ret"].fillna(50.0)
    df["pct_3yr_ret"] = df["pct_3yr_ret"].fillna(50.0)

    # Composite score
    df["composite_score"] = (
        0.25 * df["pct_1yr_ret"]
        + 0.35 * df["pct_3yr_ret"]
        + 0.25 * df["pct_5yr_ret"]
        + 0.10 * df["pct_ir_3yr"]
        + 0.05 * df["pct_sharpe_3yr"]
    )

    # Rank within category: 1 = best (highest composite_score)
    df["rank_in_category"] = df.groupby("category")["composite_score"].rank(
        ascending=False, method="min"
    ).astype(int)

    df["total_in_category"] = df.groupby("category")["schemecode"].transform("count")

    # No previous rank data yet
    df["rank_in_category_prev"] = None
    df["rank_delta"] = None

    inserts = []
    for i, r in df.iterrows():
        inserts.append((
            int(r["schemecode"]), r["amfi_name"], r["category"], r["benchmark_index"],
            r["fund_1yr_ret"] if pd.notna(r["fund_1yr_ret"]) else None,
            r["fund_3yr_ret"] if pd.notna(r["fund_3yr_ret"]) else None,
            r["fund_5yr_ret"] if pd.notna(r["fund_5yr_ret"]) else None,
            r["active_3yr_ret"] if pd.notna(r["active_3yr_ret"]) else None,
            r["information_ratio_3yr"] if pd.notna(r["information_ratio_3yr"]) else None,
            r["jensens_alpha_3yr"] if pd.notna(r["jensens_alpha_3yr"]) else None,
            r["sharpe_ratio_3yr"] if pd.notna(r["sharpe_ratio_3yr"]) else None,
            round(r["pct_1yr_ret"], 2),
            round(r["pct_3yr_ret"], 2),
            round(r["pct_5yr_ret"], 2),
            round(r["pct_ir_3yr"], 2),
            round(r["pct_sharpe_3yr"], 2),
            round(r["composite_score"], 4),
            int(r["rank_in_category"]),
            int(r["total_in_category"]),
            None,  # rank_in_category_prev
            None,  # rank_delta
            r["is_fallback_benchmark"],
            r["as_of_date"],
        ))

        if (i + 1) % 500 == 0:
            print(f"  Processed {i + 1}/{len(df)} schemes ...")

    print(f"  Prepared {len(inserts)} rows for insert")

    if inserts:
        execute_values(
            cur,
            """INSERT INTO selfmade_scheme_ranking
               (schemecode, amfi_name, category, benchmark_index,
                fund_1yr_ret, fund_3yr_ret, fund_5yr_ret, active_3yr_ret,
                information_ratio_3yr, jensens_alpha_3yr, sharpe_ratio_3yr,
                pct_1yr_ret, pct_3yr_ret, pct_5yr_ret, pct_ir_3yr, pct_sharpe_3yr,
                composite_score, rank_in_category, total_in_category,
                rank_in_category_prev, rank_delta,
                is_fallback_benchmark, as_of_date)
               VALUES %s
               ON CONFLICT (schemecode) DO UPDATE SET
                 amfi_name = EXCLUDED.amfi_name,
                 category = EXCLUDED.category,
                 benchmark_index = EXCLUDED.benchmark_index,
                 fund_1yr_ret = EXCLUDED.fund_1yr_ret,
                 fund_3yr_ret = EXCLUDED.fund_3yr_ret,
                 fund_5yr_ret = EXCLUDED.fund_5yr_ret,
                 active_3yr_ret = EXCLUDED.active_3yr_ret,
                 information_ratio_3yr = EXCLUDED.information_ratio_3yr,
                 jensens_alpha_3yr = EXCLUDED.jensens_alpha_3yr,
                 sharpe_ratio_3yr = EXCLUDED.sharpe_ratio_3yr,
                 pct_1yr_ret = EXCLUDED.pct_1yr_ret,
                 pct_3yr_ret = EXCLUDED.pct_3yr_ret,
                 pct_5yr_ret = EXCLUDED.pct_5yr_ret,
                 pct_ir_3yr = EXCLUDED.pct_ir_3yr,
                 pct_sharpe_3yr = EXCLUDED.pct_sharpe_3yr,
                 composite_score = EXCLUDED.composite_score,
                 rank_in_category = EXCLUDED.rank_in_category,
                 total_in_category = EXCLUDED.total_in_category,
                 rank_in_category_prev = EXCLUDED.rank_in_category_prev,
                 rank_delta = EXCLUDED.rank_delta,
                 is_fallback_benchmark = EXCLUDED.is_fallback_benchmark,
                 as_of_date = EXCLUDED.as_of_date""",
            inserts,
            page_size=1000,
        )

    conn.commit()

    cur.execute("""
        SELECT category, COUNT(*) as funds,
               MIN(composite_score) as min_score,
               MAX(composite_score) as max_score,
               AVG(composite_score)::numeric(8,2) as avg_score
        FROM selfmade_scheme_ranking
        GROUP BY category ORDER BY COUNT(*) DESC;
    """)
    print(f"\n  Ranking distribution:")
    print(f"  {'Category':<50} {'Funds':>5} {'MinSc':>7} {'MaxSc':>7} {'AvgSc':>7}")
    print("  " + "-" * 80)
    for row in cur.fetchall():
        print(f"  {row[0]:<50} {row[1]:>5} {float(row[2]):>7.2f} {float(row[3]):>7.2f} {float(row[4]):>7.2f}")

    cur.execute("SELECT COUNT(*) FROM selfmade_scheme_ranking;")
    total = cur.fetchone()[0]
    print(f"\n  Total ranked schemes: {total}")

    cur.close()
    conn.close()
    print("Step 4 complete.\n")


if __name__ == "__main__":
    main()
