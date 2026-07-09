"""
Step 2: Create and populate selfmade_scheme_returns.

Joins selfmade_scheme_category_benchmark with accord_fintech_mf_returns
for fund returns, and computes benchmark returns from selfmade_index_returns
TRI values. Active returns = fund - benchmark.

Idempotent — drops and recreates the table on every run.
"""

import os
from datetime import timedelta

import psycopg2
from psycopg2.extras import execute_values

DB_HOST = os.environ.get("DB_HOST", os.environ.get("POSTGRES_HOST", "localhost"))
DB_PORT = os.environ.get("DB_PORT", os.environ.get("POSTGRES_PORT", "5432"))
DB_NAME = os.environ.get("DB_NAME", os.environ.get("POSTGRES_DB", "Altstreet_AI"))
DB_USER = os.environ.get("DB_USER", os.environ.get("POSTGRES_USER", "piyushrajlenka"))
DB_PASSWORD = os.environ.get("DB_PASSWORD", os.environ.get("POSTGRES_PASSWORD", ""))


def get_nearest_tri(cur, index_name: str, target_date, max_gap_days: int = 5):
    """Find TRI value nearest to target_date within max_gap_days."""
    cur.execute("""
        SELECT tri, date FROM selfmade_index_returns
        WHERE index_name = %s
          AND date BETWEEN %s AND %s
        ORDER BY ABS(date - %s::date)
        LIMIT 1
    """, (
        index_name,
        target_date - timedelta(days=max_gap_days),
        target_date + timedelta(days=max_gap_days),
        target_date,
    ))
    row = cur.fetchone()
    return float(row[0]) if row else None


def compute_bm_return(cur, index_name: str, as_of_date, years: int):
    """Compute benchmark N-year return from TRI values."""
    end_tri = get_nearest_tri(cur, index_name, as_of_date)
    if end_tri is None:
        return None
    start_date = as_of_date - timedelta(days=years * 365)
    start_tri = get_nearest_tri(cur, index_name, start_date)
    if start_tri is None or start_tri == 0:
        return None
    return (end_tri - start_tri) / start_tri


def main():
    conn = psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASSWORD,
    )
    conn.autocommit = False
    cur = conn.cursor()

    print("Step 2: Creating selfmade_scheme_returns ...")

    cur.execute("DROP TABLE IF EXISTS selfmade_scheme_returns CASCADE;")
    cur.execute("""
        CREATE TABLE selfmade_scheme_returns (
            schemecode INTEGER UNIQUE NOT NULL,
            category VARCHAR(200),
            benchmark_index VARCHAR(300),
            as_of_date DATE,
            fund_1yr_ret NUMERIC(12,6),
            fund_2yr_ret NUMERIC(12,6),
            fund_3yr_ret NUMERIC(12,6),
            fund_4yr_ret NUMERIC(12,6),
            fund_5yr_ret NUMERIC(12,6),
            bm_1yr_ret NUMERIC(12,6),
            bm_2yr_ret NUMERIC(12,6),
            bm_3yr_ret NUMERIC(12,6),
            bm_4yr_ret NUMERIC(12,6),
            bm_5yr_ret NUMERIC(12,6),
            active_1yr_ret NUMERIC(12,6),
            active_3yr_ret NUMERIC(12,6),
            active_5yr_ret NUMERIC(12,6),
            is_fallback_benchmark BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    cur.execute("""
        SELECT cb.schemecode, cb.category, cb.benchmark_index,
               cb.is_fallback_benchmark,
               r."1yrret", r."2yearret", r."3yearret", r."4yearret", r."5yearret",
               r.c_date::date as as_of_date
        FROM selfmade_scheme_category_benchmark cb
        JOIN accord_fintech_mf_returns r ON r.schemecode = cb.schemecode
        ORDER BY cb.schemecode;
    """)
    rows = cur.fetchall()
    print(f"  Fetched {len(rows)} schemes with returns data")

    bm_cache: dict[tuple[str, object, int], float | None] = {}
    inserts = []

    for i, row in enumerate(rows):
        sc, cat, bm_idx, is_fb = row[0], row[1], row[2], row[3]
        f1, f2, f3, f4, f5 = row[4], row[5], row[6], row[7], row[8]
        as_of = row[9]

        # Convert fund returns to float or None
        f1 = float(f1) if f1 is not None else None
        f2 = float(f2) if f2 is not None else None
        f3 = float(f3) if f3 is not None else None
        f4 = float(f4) if f4 is not None else None
        f5 = float(f5) if f5 is not None else None

        # Compute benchmark returns (cached per index+date+years)
        bm_rets = {}
        for yr in [1, 2, 3, 4, 5]:
            cache_key = (bm_idx, as_of, yr)
            if cache_key not in bm_cache:
                bm_cache[cache_key] = compute_bm_return(cur, bm_idx, as_of, yr)
            bm_rets[yr] = bm_cache[cache_key]

        # Active returns
        def active(fund_r, bm_r):
            if fund_r is not None and bm_r is not None:
                return fund_r - bm_r
            return None

        inserts.append((
            sc, cat, bm_idx, as_of,
            f1, f2, f3, f4, f5,
            bm_rets[1], bm_rets[2], bm_rets[3], bm_rets[4], bm_rets[5],
            active(f1, bm_rets[1]),
            active(f3, bm_rets[3]),
            active(f5, bm_rets[5]),
            is_fb,
        ))

        if (i + 1) % 500 == 0:
            print(f"  Processed {i + 1}/{len(rows)} schemes ...")

    print(f"  Prepared {len(inserts)} rows for insert")

    if inserts:
        execute_values(
            cur,
            """INSERT INTO selfmade_scheme_returns
               (schemecode, category, benchmark_index, as_of_date,
                fund_1yr_ret, fund_2yr_ret, fund_3yr_ret, fund_4yr_ret, fund_5yr_ret,
                bm_1yr_ret, bm_2yr_ret, bm_3yr_ret, bm_4yr_ret, bm_5yr_ret,
                active_1yr_ret, active_3yr_ret, active_5yr_ret,
                is_fallback_benchmark)
               VALUES %s
               ON CONFLICT (schemecode) DO UPDATE SET
                 category = EXCLUDED.category,
                 benchmark_index = EXCLUDED.benchmark_index,
                 as_of_date = EXCLUDED.as_of_date,
                 fund_1yr_ret = EXCLUDED.fund_1yr_ret,
                 fund_2yr_ret = EXCLUDED.fund_2yr_ret,
                 fund_3yr_ret = EXCLUDED.fund_3yr_ret,
                 fund_4yr_ret = EXCLUDED.fund_4yr_ret,
                 fund_5yr_ret = EXCLUDED.fund_5yr_ret,
                 bm_1yr_ret = EXCLUDED.bm_1yr_ret,
                 bm_2yr_ret = EXCLUDED.bm_2yr_ret,
                 bm_3yr_ret = EXCLUDED.bm_3yr_ret,
                 bm_4yr_ret = EXCLUDED.bm_4yr_ret,
                 bm_5yr_ret = EXCLUDED.bm_5yr_ret,
                 active_1yr_ret = EXCLUDED.active_1yr_ret,
                 active_3yr_ret = EXCLUDED.active_3yr_ret,
                 active_5yr_ret = EXCLUDED.active_5yr_ret,
                 is_fallback_benchmark = EXCLUDED.is_fallback_benchmark""",
            inserts,
            page_size=1000,
        )

    conn.commit()

    # Summary
    cur.execute("""
        SELECT COUNT(*) as total,
               COUNT(fund_1yr_ret) as has_1yr,
               COUNT(fund_3yr_ret) as has_3yr,
               COUNT(fund_5yr_ret) as has_5yr,
               COUNT(bm_3yr_ret) as has_bm3yr,
               COUNT(active_3yr_ret) as has_active3yr
        FROM selfmade_scheme_returns;
    """)
    r = cur.fetchone()
    print(f"\n  Summary:")
    print(f"    Total rows:           {r[0]}")
    print(f"    With 1yr fund ret:    {r[1]}")
    print(f"    With 3yr fund ret:    {r[2]}")
    print(f"    With 5yr fund ret:    {r[3]}")
    print(f"    With 3yr BM ret:      {r[4]}")
    print(f"    With 3yr active ret:  {r[5]}")

    cur.close()
    conn.close()
    print("Step 2 complete.\n")


if __name__ == "__main__":
    main()
