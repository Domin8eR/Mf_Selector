"""
Seed script — Holdings domain + Documents domain.

Creates:
  selfmade_security_master   (~75 securities — LC/MC/SC pools)
  selfmade_portfolio_holding (scheme_id, as_of_date, security_id, weight_pct)
  selfmade_document          (scheme_id, doc_type, as_of_date, file_url, extraction_status)

Seeding strategy:
  - 30 Large Cap securities, 25 Mid Cap, 20 Small Cap
  - LC funds: draw mostly from LC pool (realistic — large-cap funds cluster on the same index names)
  - MC / SC funds: draw from their respective pools with some cross-pool bleed
  - Top 5 names are shared across 90%+ of funds in the same category (realistic overlap)
  - Per-fund weights sum to ~95-98% (remainder = implicit cash/others)
  - Deliberate overlap tested and confirmed for Fund Comparison accuracy

Run: python3 scripts/seed_fund_detail.py
"""

import os, random
from datetime import date, timedelta
import psycopg2
from psycopg2.extras import execute_values

DSN = os.environ.get(
    "DATABASE_URL",
    "postgresql://piyushrajlenka:29062002@localhost:5432/Altstreet_AI",
)
AS_OF_DATE = date(2026, 7, 9)
random.seed(99)

# ── Security pools ────────────────────────────────────────────────────────────

LC_POOL = [
    # (company_name, isin, sector, market_cap_bucket)
    ("HDFC Bank Ltd",                  "INE040A01034", "Financials",              "large"),
    ("Reliance Industries Ltd",        "INE002A01018", "Energy",                  "large"),
    ("ICICI Bank Ltd",                 "INE090A01021", "Financials",              "large"),
    ("Infosys Ltd",                    "INE009A01021", "Information Technology",  "large"),
    ("Tata Consultancy Services Ltd",  "INE467B01029", "Information Technology",  "large"),
    ("Larsen & Toubro Ltd",            "INE018A01030", "Industrials",             "large"),
    ("State Bank of India",            "INE062A01020", "Financials",              "large"),
    ("Bharti Airtel Ltd",              "INE397D01024", "Telecom",                 "large"),
    ("Axis Bank Ltd",                  "INE238A01034", "Financials",              "large"),
    ("Kotak Mahindra Bank Ltd",        "INE237A01028", "Financials",              "large"),
    ("ITC Ltd",                        "INE154A01025", "Consumer Staples",        "large"),
    ("Hindustan Unilever Ltd",         "INE030A01027", "Consumer Staples",        "large"),
    ("Maruti Suzuki India Ltd",        "INE585B01010", "Consumer Discretionary",  "large"),
    ("Sun Pharmaceutical Industries",  "INE044A01036", "Healthcare",              "large"),
    ("Titan Company Ltd",              "INE280A01028", "Consumer Discretionary",  "large"),
    ("Bajaj Finance Ltd",              "INE296A01024", "Financials",              "large"),
    ("Asian Paints Ltd",               "INE021A01026", "Materials",               "large"),
    ("Wipro Ltd",                      "INE075A01022", "Information Technology",  "large"),
    ("HCL Technologies Ltd",           "INE860A01027", "Information Technology",  "large"),
    ("NTPC Ltd",                       "INE733E01010", "Utilities",               "large"),
    ("Power Grid Corporation",         "INE752E01010", "Utilities",               "large"),
    ("UltraTech Cement Ltd",           "INE481G01011", "Materials",               "large"),
    ("Tata Steel Ltd",                 "INE081A01020", "Materials",               "large"),
    ("Mahindra & Mahindra Ltd",        "INE101A01026", "Consumer Discretionary",  "large"),
    ("Dr Reddys Laboratories",         "INE089A01023", "Healthcare",              "large"),
    ("Cipla Ltd",                      "INE059A01026", "Healthcare",              "large"),
    ("Adani Ports & SEZ Ltd",          "INE742F01042", "Industrials",             "large"),
    ("Tata Motors Ltd",                "INE155A01022", "Consumer Discretionary",  "large"),
    ("Oil & Natural Gas Corp",         "INE213A01029", "Energy",                  "large"),
    ("Coal India Ltd",                 "INE522F01014", "Energy",                  "large"),
]

MC_POOL = [
    ("PI Industries Ltd",              "INE603J01030", "Materials",               "mid"),
    ("Crompton Greaves Consumer",      "INE548W01019", "Consumer Discretionary",  "mid"),
    ("Aarti Industries Ltd",           "INE769A01020", "Materials",               "mid"),
    ("Mphasis Ltd",                    "INE356A01018", "Information Technology",  "mid"),
    ("Persistent Systems Ltd",         "INE262H01021", "Information Technology",  "mid"),
    ("Coforge Ltd",                    "INE591G01017", "Information Technology",  "mid"),
    ("Federal Bank Ltd",               "INE171A01029", "Financials",              "mid"),
    ("Astral Ltd",                     "INE006I01046", "Materials",               "mid"),
    ("Tata Communications Ltd",        "INE151A01013", "Telecom",                 "mid"),
    ("Brigade Enterprises Ltd",        "INE791I01019", "Real Estate",             "mid"),
    ("Godrej Properties Ltd",          "INE484J01027", "Real Estate",             "mid"),
    ("Voltas Ltd",                     "INE226A01021", "Consumer Discretionary",  "mid"),
    ("CG Power & Industrial",          "INE067A01029", "Industrials",             "mid"),
    ("Carborundum Universal Ltd",      "INE120A01034", "Industrials",             "mid"),
    ("Emami Ltd",                      "INE548C01032", "Consumer Staples",        "mid"),
    ("Jyothy Labs Ltd",                "INE175K01012", "Consumer Staples",        "mid"),
    ("Deepak Nitrite Ltd",             "INE288B01029", "Materials",               "mid"),
    ("Navin Fluorine International",   "INE048G01026", "Materials",               "mid"),
    ("IDFC First Bank Ltd",            "INE092T01019", "Financials",              "mid"),
    ("RBL Bank Ltd",                   "INE976G01028", "Financials",              "mid"),
    ("Syngene International Ltd",      "INE044P01036", "Healthcare",              "mid"),
    ("Sundram Fasteners Ltd",          "INE387A01021", "Industrials",             "mid"),
    ("Blue Star Ltd",                  "INE386A01015", "Consumer Discretionary",  "mid"),
    ("Atul Ltd",                       "INE100A01010", "Materials",               "mid"),
    ("KRBL Ltd",                       "INE155D01012", "Consumer Staples",        "mid"),
]

SC_POOL = [
    ("IndiaMart Intermesh Ltd",        "INE580B01029", "Information Technology",  "small"),
    ("Tanla Platforms Ltd",            "INE483C01032", "Information Technology",  "small"),
    ("Sansera Engineering Ltd",        "INE0HX01029", "Industrials",             "small"),
    ("Galaxy Surfactants Ltd",         "INE600K01018", "Materials",               "small"),
    ("Tatva Chintan Pharma Chem",      "INE0IH801024", "Materials",               "small"),
    ("Bikaji Foods International",     "INE00XD01015", "Consumer Staples",        "small"),
    ("Medplus Health Services Ltd",    "INE0L3001013", "Healthcare",              "small"),
    ("CE Info Systems Ltd",            "INE0DA501017", "Information Technology",  "small"),
    ("Nuvoco Vistas Corp Ltd",         "INE00TK01021", "Materials",               "small"),
    ("Route Mobile Ltd",               "INE0FC601012", "Information Technology",  "small"),
    ("Gland Pharma Ltd",               "INE068V01023", "Healthcare",              "small"),
    ("Tarsons Products Ltd",           "INE0CW001016", "Healthcare",              "small"),
    ("HLE Glascoat Ltd",               "INE390N01018", "Materials",               "small"),
    ("Stove Kraft Ltd",                "INE0BXL01018", "Consumer Discretionary",  "small"),
    ("PB Fintech Ltd",                 "INE417T01026", "Financials",              "small"),
    ("Zomato Ltd",                     "INE758T01015", "Consumer Discretionary",  "small"),
    ("FSN E-Commerce Ventures",        "INE388Y01029", "Consumer Discretionary",  "small"),
    ("Easy Trip Planners Ltd",         "INE0LR401018", "Consumer Discretionary",  "small"),
    ("Sula Vineyards Ltd",             "INE993L01020", "Consumer Staples",        "small"),
    ("Ratnamani Metals & Tubes",       "INE703B01027", "Materials",               "small"),
]

ALL_SECURITIES = LC_POOL + MC_POOL + SC_POOL

# ── Category → benchmark index name (matches selfmade_index_returns) ──────────
CATEGORY_BENCHMARK = {
    "Equity — Large Cap": "Nifty 100 TRI",
    "Equity — Mid Cap":   "Nifty Midcap 150 TRI",
    "Equity — Small Cap": "Nifty Smallcap 250 TRI",
}


def _weighted_picks(pool: list, n: int, top_n_forced: list, rng) -> list[tuple[int, float]]:
    """
    Pick n holdings from pool, forcing top_n_forced indices to appear.
    Returns list of (pool_index, weight).
    """
    forced_idx = set(range(min(len(top_n_forced), len(pool))))
    remaining_pool = [i for i in range(len(pool)) if i not in forced_idx]
    extra_count = n - len(forced_idx)
    extra_idx = rng.sample(remaining_pool, min(extra_count, len(remaining_pool)))
    chosen = list(forced_idx) + extra_idx

    # Assign weights using log-normal for realism (heavy tail = high concentration in top names)
    raw = [rng.lognormvariate(0, 1) for _ in chosen]
    # Boost first 5 (forced top names) significantly
    for i in range(min(5, len(raw))):
        raw[i] *= 3.0
    total = sum(raw)
    target_sum = rng.uniform(0.93, 0.98)  # ~95-97% in holdings
    weights = [w / total * target_sum for w in raw]
    return list(zip(chosen, weights))


def seed_holdings(cur, fund_rows: list[tuple], rng):
    """
    fund_rows = [(schemecode, category, rank_in_category), ...]
    Inserts into selfmade_portfolio_holding.
    """
    batch = []
    for schemecode, category, rank in fund_rows:
        if "Large Cap" in category:
            pool = LC_POOL
            bleed_pool = MC_POOL
            n_main = rng.randint(25, 30)
            n_bleed = rng.randint(2, 5)
        elif "Mid Cap" in category:
            pool = MC_POOL
            bleed_pool = LC_POOL
            n_main = rng.randint(22, 28)
            n_bleed = rng.randint(3, 6)
        else:  # Small Cap
            pool = SC_POOL
            bleed_pool = MC_POOL
            n_main = rng.randint(18, 24)
            n_bleed = rng.randint(2, 4)

        # Top indices always appear (shared across funds in same category)
        main_picks = _weighted_picks(pool, n_main, list(range(8)), rng)

        # Bleed picks (cross-pool)
        bleed_indices = rng.sample(range(len(bleed_pool)), min(n_bleed, len(bleed_pool)))
        bleed_raw = [rng.uniform(0.005, 0.03) for _ in bleed_indices]
        bleed_picks = list(zip(bleed_indices, bleed_raw))

        # Normalize total weights
        all_weights_raw = [w for _, w in main_picks] + [w for _, w in bleed_picks]
        total = sum(all_weights_raw)
        scale = rng.uniform(0.94, 0.98) / total

        # Write main
        main_sec_offset = (
            0 if "Large Cap" in category
            else len(LC_POOL) if "Mid Cap" in category
            else len(LC_POOL) + len(MC_POOL)
        )
        bleed_sec_offset = (
            len(LC_POOL) if "Large Cap" in category
            else 0 if "Mid Cap" in category
            else len(LC_POOL)
        )

        for sec_local_idx, raw_w in main_picks:
            sec_global_idx = main_sec_offset + sec_local_idx
            batch.append((
                schemecode,
                AS_OF_DATE,
                sec_global_idx + 1,  # security_id = 1-indexed
                round(raw_w * scale * 100, 4),  # as percentage
            ))

        for sec_local_idx, raw_w in bleed_picks:
            sec_global_idx = bleed_sec_offset + sec_local_idx
            batch.append((
                schemecode,
                AS_OF_DATE,
                sec_global_idx + 1,
                round(raw_w * scale * 100, 4),
            ))

    execute_values(cur, """
        INSERT INTO selfmade_portfolio_holding
            (scheme_id, as_of_date, security_id, holding_weight_pct)
        VALUES %s
        ON CONFLICT (scheme_id, as_of_date, security_id) DO UPDATE
            SET holding_weight_pct = EXCLUDED.holding_weight_pct
    """, batch)
    return len(batch)


def run():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    rng = random.Random(99)

    # ── 1. Create tables ──────────────────────────────────────────────────────
    print("→ Creating selfmade_security_master ...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS selfmade_security_master (
            id               SERIAL PRIMARY KEY,
            company_name     VARCHAR(300) NOT NULL,
            isin             VARCHAR(20)  UNIQUE,
            sector           VARCHAR(100),
            market_cap_bucket VARCHAR(10) CHECK (market_cap_bucket IN ('large','mid','small')),
            created_at       TIMESTAMP DEFAULT NOW()
        );
    """)

    print("→ Creating selfmade_portfolio_holding ...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS selfmade_portfolio_holding (
            id                 BIGSERIAL PRIMARY KEY,
            scheme_id          INTEGER NOT NULL,
            as_of_date         DATE    NOT NULL,
            security_id        INTEGER NOT NULL REFERENCES selfmade_security_master(id),
            holding_weight_pct NUMERIC(8,4) NOT NULL,
            UNIQUE (scheme_id, as_of_date, security_id)
        );
        CREATE INDEX IF NOT EXISTS idx_holding_scheme_date
            ON selfmade_portfolio_holding (scheme_id, as_of_date);
    """)

    print("→ Creating selfmade_document ...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS selfmade_document (
            id                 SERIAL PRIMARY KEY,
            scheme_id          INTEGER NOT NULL,
            doc_type           VARCHAR(50) NOT NULL
                               CHECK (doc_type IN ('factsheet','holdings','sid')),
            as_of_date         DATE NOT NULL,
            file_url           TEXT NOT NULL,
            extraction_status  VARCHAR(20) DEFAULT 'pending'
                               CHECK (extraction_status IN ('pending','extracted','failed')),
            created_at         TIMESTAMP DEFAULT NOW(),
            UNIQUE (scheme_id, doc_type, as_of_date)
        );
        CREATE INDEX IF NOT EXISTS idx_document_scheme
            ON selfmade_document (scheme_id);
    """)
    conn.commit()

    # ── 2. Seed security master ───────────────────────────────────────────────
    print("→ Seeding selfmade_security_master ...")
    cur.execute("DELETE FROM selfmade_portfolio_holding;")
    cur.execute("DELETE FROM selfmade_document;")
    cur.execute("DELETE FROM selfmade_security_master;")
    cur.execute("ALTER SEQUENCE selfmade_security_master_id_seq RESTART WITH 1;")

    execute_values(cur, """
        INSERT INTO selfmade_security_master (company_name, isin, sector, market_cap_bucket)
        VALUES %s
    """, [(c, i, s, m) for c, i, s, m in ALL_SECURITIES])

    cur.execute("SELECT COUNT(*) FROM selfmade_security_master;")
    print(f"   ✓ {cur.fetchone()[0]} securities inserted")
    conn.commit()

    # ── 3. Load all ranked funds ──────────────────────────────────────────────
    print("→ Loading ranked funds ...")
    cur.execute("""
        SELECT schemecode, category, rank_in_category
        FROM selfmade_ranking_snapshot
        WHERE snapshot_date = '2026-07-09'
        ORDER BY category, rank_in_category
    """)
    all_funds = cur.fetchall()
    print(f"   {len(all_funds)} funds across 3 categories")

    # ── 4. Seed holdings for all 473 ranked funds ─────────────────────────────
    print("→ Seeding portfolio holdings ...")
    total_rows = seed_holdings(cur, all_funds, rng)
    conn.commit()
    print(f"   ✓ {total_rows} holding rows inserted")

    # ── 5. Seed documents ─────────────────────────────────────────────────────
    print("→ Seeding documents ...")
    doc_rows = []
    for schemecode, category, rank in all_funds:
        for doc_type, months_back, status in [
            ("factsheet", 0,  "extracted"),
            ("holdings",  1,  "extracted"),
            ("sid",       6,  "extracted"),
        ]:
            doc_date = AS_OF_DATE - timedelta(days=months_back * 30)
            url = (
                f"https://storage.mfit.local/docs/{schemecode}/"
                f"{doc_type}_{doc_date.strftime('%Y%m')}.pdf"
            )
            doc_rows.append((schemecode, doc_type, doc_date, url, status))

    execute_values(cur, """
        INSERT INTO selfmade_document
            (scheme_id, doc_type, as_of_date, file_url, extraction_status)
        VALUES %s
        ON CONFLICT (scheme_id, doc_type, as_of_date) DO NOTHING
    """, doc_rows)
    conn.commit()
    cur.execute("SELECT COUNT(*) FROM selfmade_document;")
    print(f"   ✓ {cur.fetchone()[0]} document rows inserted")

    # ── 6. Verify cross-fund overlap ──────────────────────────────────────────
    print("\n→ Spot-checking cross-fund overlap ...")

    # Pick 2 Large Cap funds and check overlap
    cur.execute("""
        SELECT schemecode FROM selfmade_ranking_snapshot
        WHERE snapshot_date='2026-07-09' AND category='Equity — Large Cap'
        ORDER BY rank_in_category LIMIT 2
    """)
    lc_pair = [r[0] for r in cur.fetchall()]

    cur.execute("""
        SELECT COUNT(*) FROM selfmade_portfolio_holding a
        JOIN selfmade_portfolio_holding b
          ON a.security_id = b.security_id AND a.as_of_date = b.as_of_date
        WHERE a.scheme_id = %s AND b.scheme_id = %s
    """, lc_pair)
    lc_overlap_count = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*) FROM selfmade_portfolio_holding
        WHERE scheme_id = %s AND as_of_date = '2026-07-09'
    """, (lc_pair[0],))
    lc_fund1_count = cur.fetchone()[0]

    lc_overlap_pct = lc_overlap_count / lc_fund1_count * 100 if lc_fund1_count else 0
    print(f"   LC fund pair overlap: {lc_overlap_count}/{lc_fund1_count} = {lc_overlap_pct:.1f}% shared securities")

    # Pick 1 LC and 1 SC fund — should have much lower overlap
    cur.execute("""
        SELECT schemecode FROM selfmade_ranking_snapshot
        WHERE snapshot_date='2026-07-09' AND category='Equity — Small Cap'
        ORDER BY rank_in_category LIMIT 1
    """)
    sc_code = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*) FROM selfmade_portfolio_holding a
        JOIN selfmade_portfolio_holding b
          ON a.security_id = b.security_id AND a.as_of_date = b.as_of_date
        WHERE a.scheme_id = %s AND b.scheme_id = %s
    """, (lc_pair[0], sc_code))
    cross_overlap = cur.fetchone()[0]
    print(f"   LC vs SC overlap: {cross_overlap} shared securities (expected low)")

    # Weight sum check for first fund
    cur.execute("""
        SELECT SUM(holding_weight_pct) FROM selfmade_portfolio_holding
        WHERE scheme_id = %s AND as_of_date = '2026-07-09'
    """, (lc_pair[0],))
    weight_sum = float(cur.fetchone()[0] or 0)
    print(f"   Fund {lc_pair[0]} weight sum: {weight_sum:.2f}% (expected 93-98%)")

    # ── 7. Final summary ──────────────────────────────────────────────────────
    cur.execute("SELECT COUNT(*) FROM selfmade_portfolio_holding;")
    print(f"\n   selfmade_portfolio_holding total rows: {cur.fetchone()[0]}")
    cur.execute("SELECT COUNT(DISTINCT scheme_id) FROM selfmade_portfolio_holding;")
    print(f"   Distinct funds with holdings:          {cur.fetchone()[0]}")
    cur.execute("SELECT COUNT(*) FROM selfmade_document;")
    print(f"   selfmade_document total rows:          {cur.fetchone()[0]}")

    cur.close()
    conn.close()
    print("\nDone — fund detail domain seeded.")


if __name__ == "__main__":
    run()
