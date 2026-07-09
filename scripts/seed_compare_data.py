"""
seed_compare_data.py — Seed comparison-related tables.

Idempotent: safe to re-run.

Creates / seeds:
  1. selfmade_benchmark_holding   — benchmark index weights
  2. selfmade_portfolio_holding   — historical snapshot for 2026-01-09
  3. selfmade_expense_ratio       — synthetic expense ratios for 473 ranked funds
"""

from __future__ import annotations

import random
import sys
from datetime import date

import psycopg2
from psycopg2.extras import execute_values

# ── DB connection ─────────────────────────────────────────────────────────────

DB_URL = "postgresql://piyushrajlenka:29062002@localhost:5432/Altstreet_AI"

def get_conn():
    return psycopg2.connect(DB_URL)


# ══════════════════════════════════════════════════════════════════════════════
# 1a. selfmade_benchmark_holding
# ══════════════════════════════════════════════════════════════════════════════

BENCHMARK_HOLDING_DDL = """
CREATE TABLE IF NOT EXISTS selfmade_benchmark_holding (
    id BIGSERIAL PRIMARY KEY,
    benchmark_index VARCHAR(300) NOT NULL,
    security_id INTEGER NOT NULL REFERENCES selfmade_security_master(id),
    weight_pct NUMERIC(8,4) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(benchmark_index, security_id)
);
"""


def _build_nifty100_weights() -> list[tuple[str, int, float]]:
    """
    Nifty 100 TRI: 30 LC securities (ids 1-30) + 10 MC securities (ids 31-40).
    Realistic market-cap weights for LC, tiny weights for MC addition.
    """
    bm = "Nifty 100 TRI"
    weights: dict[int, float] = {}

    # LC securities: ids 1-30
    # Ids 1-5: 6-10% each
    tier1 = {1: 9.8, 2: 9.2, 3: 8.5, 4: 7.4, 5: 6.8}
    # Ids 6-10: 3-5% each
    tier2 = {6: 4.9, 7: 4.3, 8: 3.9, 9: 3.5, 10: 3.1}
    # Ids 11-20: 1-3% each
    tier3_vals = [2.8, 2.5, 2.3, 2.1, 1.9, 1.7, 1.5, 1.4, 1.2, 1.1]
    tier3 = {11 + i: v for i, v in enumerate(tier3_vals)}
    # Ids 21-30: 0.3-1% each
    tier4_vals = [0.95, 0.85, 0.75, 0.70, 0.65, 0.55, 0.50, 0.45, 0.40, 0.35]
    tier4 = {21 + i: v for i, v in enumerate(tier4_vals)}

    weights.update(tier1)
    weights.update(tier2)
    weights.update(tier3)
    weights.update(tier4)

    # MC securities (ids 31-40): very small weights 0.2-0.8%
    mc_raw = {31: 0.75, 32: 0.65, 33: 0.60, 34: 0.55, 35: 0.50,
              36: 0.45, 37: 0.40, 38: 0.35, 39: 0.28, 40: 0.22}
    weights.update(mc_raw)

    # Normalize to exactly 100.0
    total = sum(weights.values())
    factor = 100.0 / total
    normalized = {sec_id: round(w * factor, 4) for sec_id, w in weights.items()}

    # Fix rounding: adjust last security
    diff = round(100.0 - sum(normalized.values()), 4)
    last_key = max(normalized.keys())
    normalized[last_key] = round(normalized[last_key] + diff, 4)

    return [(bm, sec_id, w) for sec_id, w in normalized.items()]


def _build_nifty_midcap150_weights() -> list[tuple[str, int, float]]:
    """
    Nifty Midcap 150 TRI: 25 MC securities (ids 31-55) ~4% each + 10 SC (ids 56-65) small.
    """
    bm = "Nifty Midcap 150 TRI"
    weights: dict[int, float] = {}

    # MC securities (ids 31-55): ~4% each
    for i, sec_id in enumerate(range(31, 56)):
        weights[sec_id] = 4.0 + (0.1 if i < 5 else -0.05 if i >= 20 else 0.0)

    # SC securities (ids 56-65): smaller weights
    sc_raw = [1.0, 0.9, 0.85, 0.80, 0.75, 0.70, 0.65, 0.60, 0.55, 0.50]
    for i, sec_id in enumerate(range(56, 66)):
        weights[sec_id] = sc_raw[i]

    # Normalize to 100.0
    total = sum(weights.values())
    factor = 100.0 / total
    normalized = {sec_id: round(w * factor, 4) for sec_id, w in weights.items()}

    diff = round(100.0 - sum(normalized.values()), 4)
    last_key = max(normalized.keys())
    normalized[last_key] = round(normalized[last_key] + diff, 4)

    return [(bm, sec_id, w) for sec_id, w in normalized.items()]


def _build_nifty_smallcap250_weights() -> list[tuple[str, int, float]]:
    """
    Nifty Smallcap 250 TRI: 20 SC securities (ids 56-75) ~5% each.
    """
    bm = "Nifty Smallcap 250 TRI"
    weights: dict[int, float] = {}

    for i, sec_id in enumerate(range(56, 76)):
        # Slight variation: first few a bit heavier
        weights[sec_id] = 5.2 if i < 4 else (5.0 if i < 12 else 4.8)

    # Normalize to 100.0
    total = sum(weights.values())
    factor = 100.0 / total
    normalized = {sec_id: round(w * factor, 4) for sec_id, w in weights.items()}

    diff = round(100.0 - sum(normalized.values()), 4)
    last_key = max(normalized.keys())
    normalized[last_key] = round(normalized[last_key] + diff, 4)

    return [(bm, sec_id, w) for sec_id, w in normalized.items()]


def seed_benchmark_holdings(conn) -> int:
    cur = conn.cursor()
    cur.execute(BENCHMARK_HOLDING_DDL)
    conn.commit()

    all_rows: list[tuple[str, int, float]] = []
    all_rows.extend(_build_nifty100_weights())
    all_rows.extend(_build_nifty_midcap150_weights())
    all_rows.extend(_build_nifty_smallcap250_weights())

    # Verify sums
    for bm_name in ["Nifty 100 TRI", "Nifty Midcap 150 TRI", "Nifty Smallcap 250 TRI"]:
        bm_rows = [(bm, s, w) for bm, s, w in all_rows if bm == bm_name]
        total = sum(w for _, _, w in bm_rows)
        print(f"  {bm_name}: {len(bm_rows)} securities, total weight = {total:.4f}%")

    inserted = 0
    for bm, sec_id, w in all_rows:
        cur.execute("""
            INSERT INTO selfmade_benchmark_holding (benchmark_index, security_id, weight_pct)
            VALUES (%s, %s, %s)
            ON CONFLICT (benchmark_index, security_id) DO UPDATE SET weight_pct = EXCLUDED.weight_pct
        """, (bm, sec_id, w))
        inserted += 1

    conn.commit()
    cur.close()
    return inserted


# ══════════════════════════════════════════════════════════════════════════════
# 1b. Historical holdings snapshot: 2026-01-09
# ══════════════════════════════════════════════════════════════════════════════

HIST_DATE = date(2026, 1, 9)
CURRENT_DATE = date(2026, 7, 9)


def _get_cap_bucket_pool(conn) -> dict[str, list[int]]:
    """Return {market_cap_bucket: [security_ids]} from selfmade_security_master."""
    cur = conn.cursor()
    cur.execute("SELECT id, market_cap_bucket FROM selfmade_security_master ORDER BY id")
    pool: dict[str, list[int]] = {"large": [], "mid": [], "small": []}
    for row in cur.fetchall():
        sec_id, bucket = row
        pool[bucket].append(sec_id)
    cur.close()
    return pool


def _get_fund_bucket(conn) -> dict[int, str]:
    """Return {schemecode: market_cap_bucket} for all ranked funds."""
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT ON (schemecode) schemecode, category
        FROM selfmade_ranking_snapshot
        ORDER BY schemecode, snapshot_date DESC
    """)
    cat_to_bucket = {
        "Equity — Large Cap": "large",
        "Equity — Mid Cap": "mid",
        "Equity — Small Cap": "small",
    }
    result = {}
    for sc, cat in cur.fetchall():
        result[sc] = cat_to_bucket.get(cat, "large")
    cur.close()
    return result


def _get_current_holdings(conn) -> dict[int, list[tuple[int, float]]]:
    """
    Return {scheme_id: [(security_id, weight_pct)]} for CURRENT_DATE.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT scheme_id, security_id, holding_weight_pct
        FROM selfmade_portfolio_holding
        WHERE as_of_date = %s
        ORDER BY scheme_id, holding_weight_pct DESC
    """, (CURRENT_DATE,))
    holdings: dict[int, list[tuple[int, float]]] = {}
    for sc, sec_id, wt in cur.fetchall():
        holdings.setdefault(sc, []).append((sec_id, float(wt)))
    cur.close()
    return holdings


def seed_historical_holdings(conn) -> int:
    """Seed selfmade_portfolio_holding rows for HIST_DATE (2026-01-09)."""
    cap_pool = _get_cap_bucket_pool(conn)
    fund_bucket = _get_fund_bucket(conn)
    current_holdings = _get_current_holdings(conn)

    # Check which funds already have historical rows
    cur = conn.cursor()
    cur.execute(
        "SELECT DISTINCT scheme_id FROM selfmade_portfolio_holding WHERE as_of_date = %s",
        (HIST_DATE,)
    )
    already_done = {row[0] for row in cur.fetchall()}
    cur.close()

    funds_to_process = [sc for sc in current_holdings if sc not in already_done]
    print(f"  Funds to process for {HIST_DATE}: {len(funds_to_process)} (skipping {len(already_done)} already done)")

    if not funds_to_process:
        return 0

    rows_to_insert: list[tuple] = []

    for sc in funds_to_process:
        holdings = current_holdings[sc]
        bucket = fund_bucket.get(sc, "large")
        pool = cap_pool[bucket]
        current_sec_ids = {h[0] for h in holdings}

        # Step 1: Perturb weights
        perturbed: list[tuple[int, float]] = []
        for sec_id, wt in holdings:
            factor = random.Random(sc * 7 + sec_id).uniform(0.82, 1.18)
            perturbed.append((sec_id, wt * factor))

        # Step 2: Drop ~10% of holdings deterministically
        kept: list[tuple[int, float]] = []
        for sec_id, wt in perturbed:
            if random.Random(sc * 13 + sec_id).random() >= 0.10:
                kept.append((sec_id, wt))

        if not kept:
            kept = perturbed  # safety fallback

        # Step 3: Add 1-3 new holdings from the same bucket
        unused_in_bucket = [s for s in pool if s not in current_sec_ids]
        n_new = random.Random(sc * 17).randint(1, 3)
        new_holdings: list[tuple[int, float]] = []
        for i in range(min(n_new, len(unused_in_bucket))):
            new_sec = unused_in_bucket[i]
            # Small weight: ~0.5-1.5% of a typical holding
            avg_wt = sum(w for _, w in kept) / max(len(kept), 1) if kept else 2.0
            new_wt = avg_wt * random.Random(sc * 19 + new_sec).uniform(0.1, 0.3)
            new_holdings.append((new_sec, max(new_wt, 0.1)))

        combined = kept + new_holdings

        # Step 4: Re-normalize to same total as current
        current_total = sum(w for _, w in holdings)
        new_total = sum(w for _, w in combined)
        if new_total > 0 and current_total > 0:
            factor = current_total / new_total
            combined = [(s, w * factor) for s, w in combined]

        for sec_id, wt in combined:
            rows_to_insert.append((sc, HIST_DATE, sec_id, round(wt, 4)))

    # Bulk insert
    if rows_to_insert:
        cur = conn.cursor()
        execute_values(
            cur,
            """
            INSERT INTO selfmade_portfolio_holding (scheme_id, as_of_date, security_id, holding_weight_pct)
            VALUES %s
            ON CONFLICT DO NOTHING
            """,
            rows_to_insert,
            page_size=5000,
        )
        conn.commit()
        cur.close()

    return len(rows_to_insert)


# ══════════════════════════════════════════════════════════════════════════════
# 1c. selfmade_expense_ratio
# ══════════════════════════════════════════════════════════════════════════════

EXPENSE_RATIO_DDL = """
CREATE TABLE IF NOT EXISTS selfmade_expense_ratio (
    schemecode INTEGER PRIMARY KEY,
    expense_ratio_pct NUMERIC(5,2) NOT NULL,
    category VARCHAR(200),
    as_of_date DATE DEFAULT CURRENT_DATE,
    created_at TIMESTAMP DEFAULT NOW()
);
"""


def seed_expense_ratios(conn) -> int:
    cur = conn.cursor()
    cur.execute(EXPENSE_RATIO_DDL)
    conn.commit()

    # Get all 473 ranked funds with category
    cur.execute("""
        SELECT DISTINCT ON (schemecode) schemecode, category
        FROM selfmade_ranking_snapshot
        ORDER BY schemecode, snapshot_date DESC
    """)
    funds = cur.fetchall()

    category_params = {
        "Equity — Large Cap": (0.60, 0.40, 1.20),
        "Equity — Mid Cap":   (0.90, 0.65, 1.80),
        "Equity — Small Cap": (1.10, 0.80, 2.20),
    }

    rows: list[tuple] = []
    for sc, cat in funds:
        base, lo, hi = category_params.get(cat, (0.80, 0.40, 1.80))
        noise = random.Random(sc * 3).uniform(-0.20, 0.60)
        er = max(lo, min(hi, base + noise))
        rows.append((sc, round(er, 2), cat))

    execute_values(
        cur,
        """
        INSERT INTO selfmade_expense_ratio (schemecode, expense_ratio_pct, category)
        VALUES %s
        ON CONFLICT (schemecode) DO UPDATE
            SET expense_ratio_pct = EXCLUDED.expense_ratio_pct,
                category = EXCLUDED.category
        """,
        rows,
    )
    conn.commit()
    cur.close()
    return len(rows)


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    print("=== seed_compare_data.py ===")
    conn = get_conn()

    print("\n[1a] Seeding selfmade_benchmark_holding …")
    n = seed_benchmark_holdings(conn)
    print(f"     Done: {n} rows upserted")

    print(f"\n[1b] Seeding historical holdings (as_of_date = {HIST_DATE}) …")
    n = seed_historical_holdings(conn)
    print(f"     Done: {n} rows inserted")

    print("\n[1c] Seeding selfmade_expense_ratio …")
    n = seed_expense_ratios(conn)
    print(f"     Done: {n} rows upserted")

    # ── Verification ──────────────────────────────────────────────────────────
    print("\n=== Verification ===")
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM selfmade_benchmark_holding")
    bh_count = cur.fetchone()[0]
    print(f"selfmade_benchmark_holding rows: {bh_count}")

    cur.execute(
        "SELECT COUNT(*) FROM selfmade_portfolio_holding WHERE as_of_date = %s",
        (HIST_DATE,)
    )
    ph_count = cur.fetchone()[0]
    print(f"selfmade_portfolio_holding rows for {HIST_DATE}: {ph_count}")

    cur.execute("SELECT COUNT(*) FROM selfmade_expense_ratio")
    er_count = cur.fetchone()[0]
    print(f"selfmade_expense_ratio rows: {er_count}")

    cur.close()
    conn.close()

    print("\n=== seed_compare_data.py complete ===")


if __name__ == "__main__":
    main()
