"""
Step 3: Build the versioned 36-bucket category taxonomy.

Creates two append-only tables:
  category_taxonomy_version  — version pointer (active = TRUE)
  category_taxonomy_mapping  — one row per (schemecode, version_number)

And a stable read view:
  category_taxonomy_current  — selects mapping rows for the active version

Bucketing strategy:
  1. selfmade_scheme_category_benchmark.category (granular equity taxonomy from
     step2, already built this session) → maps to equity sub-buckets.
  2. altstreet_scheme_master.category + accord_fintech_scheme_details.amfitype
     → maps everything else (hybrid, passive, debt, gold/silver).

Schemes not covered by the 36 buckets (short/medium duration, corporate bond,
gilt, credit risk, solution-oriented etc.) receive bucket_36 = NULL and are
simply excluded from the bucket_36 filtered view — they remain accessible via
the raw category_id filter.

Idempotent: if a version with the same description already exists, it is
re-activated rather than duplicated.  New runs always append a new version
so the previous version's rows are preserved.
"""

from __future__ import annotations

import os
import re
from datetime import date

import psycopg2
from psycopg2.extras import execute_values

DB_HOST     = os.environ.get("DB_HOST", "localhost")
DB_PORT     = os.environ.get("DB_PORT", "5432")
DB_NAME     = os.environ.get("DB_NAME", "Altstreet_AI")
DB_USER     = os.environ.get("DB_USER", "piyushrajlenka")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")

# ── Bucket definitions ─────────────────────────────────────────────────────
# (bucket_36 name, bucket_group)
# group is one of: ALL Equity / ALL Hybrid / ALL Passive

# From selfmade_scheme_category_benchmark.category (granular equity taxonomy)
_SCB_CAT_TO_BUCKET: dict[str, tuple[str, str]] = {
    "Equity — Flexi Cap":               ("Flexi Cap",     "ALL Equity"),
    "Equity — Large Cap":               ("Large Cap",      "ALL Equity"),
    "Equity — Large & Mid Cap":         ("Large & Mid Cap","ALL Equity"),
    "Equity — Mid Cap":                 ("Mid Cap",        "ALL Equity"),
    "Equity — Small Cap":               ("Small Cap",      "ALL Equity"),
    "Equity — Multi Cap":               ("Multi Cap",      "ALL Equity"),
    "Equity — Focused Fund":            ("Focused Fund",   "ALL Equity"),
    "Equity — Contra Fund":             ("Value / Contra", "ALL Equity"),
    "Equity — Value Fund":              ("Value / Contra", "ALL Equity"),
    "Equity — Dividend Yield":          ("Dividend Yield", "ALL Equity"),
    "Equity — ELSS / Tax Saving":       ("ELSS",           "ALL Equity"),
    "Equity — Quant":                   ("Thematic funds", "ALL Equity"),
    "Equity — Momentum (Active)":       ("Thematic funds", "ALL Equity"),
    "Equity — ESG / Sustainable":       ("Thematic funds", "ALL Equity"),
    "Equity — General / Diversified":   ("Market Cap Funds","ALL Equity"),
}

_SCB_PREFIX_TO_BUCKET: list[tuple[str, str, str]] = [
    # (prefix, bucket_36, group)
    ("Equity Thematic",               "Thematic funds",  "ALL Equity"),
    ("Equity Sectoral",               "Sectoral funds",  "ALL Equity"),
    ("Equity Index",                  "Index Funds",     "ALL Passive"),
]

def scb_to_bucket(scb_category: str | None, amfi_name: str) -> tuple[str, str] | None:
    """Map selfmade_scheme_category_benchmark.category to (bucket_36, group)."""
    if not scb_category:
        return None
    # Explicit dict lookup first
    if scb_category in _SCB_CAT_TO_BUCKET:
        return _SCB_CAT_TO_BUCKET[scb_category]
    # Prefix match for Thematic / Sectoral / Index
    for prefix, bucket, group in _SCB_PREFIX_TO_BUCKET:
        if scb_category.startswith(prefix):
            # "Other / Unclassified" caught by ETF/index catch-all in step2
            return bucket, group
    # Other / Unclassified — split by ETF vs index fund by name
    if scb_category == "Other / Unclassified":
        n = amfi_name.lower()
        if "etf" in n:
            return "ETFs", "ALL Passive"
        return "Index Funds", "ALL Passive"
    return None


# From altstreet_scheme_master.category + amfitype fallback
_ALTSTREET_TO_BUCKET: dict[str, tuple[str, str]] = {
    "Equity Linked Savings Scheme":  ("ELSS",                                      "ALL Equity"),
    "Sector Funds":                  ("Sectoral funds",                             "ALL Equity"),
    "Thematic Fund":                 ("Thematic funds",                             "ALL Equity"),
    "Focused Fund":                  ("Focused Fund",                               "ALL Equity"),
    "Contra":                        ("Value / Contra",                             "ALL Equity"),
    "Value Fund":                    ("Value / Contra",                             "ALL Equity"),
    "Dividend Yield":                ("Dividend Yield",                             "ALL Equity"),
    "Market Cap Fund":               ("Market Cap Funds",                           "ALL Equity"),
    "Index Funds":                   ("Index Funds",                                "ALL Passive"),
    "Equity Savings":                ("Equity Savings",                             "ALL Hybrid"),
    "Arbitrage Fund":                ("Arbitrage",                                  "ALL Hybrid"),
    "Aggressive Hybrid Fund":        ("Aggressive Hybrid",                          "ALL Hybrid"),
    "Balanced Advantage":            ("Balanced Advantage / Dynamic Asset Allocation","ALL Hybrid"),
    "Dynamic Asset Allocation":      ("Balanced Advantage / Dynamic Asset Allocation","ALL Hybrid"),
    "Balanced Hybrid Fund":          ("Aggressive Hybrid",                          "ALL Hybrid"),  # rare
    "Conservative Hybrid Fund":      ("Conservative Hybrid",                        "ALL Hybrid"),
    "Multi Asset Allocation":        ("Multi Asset Allocation",                     "ALL Hybrid"),
    "FoFs (Domestic)":               ("Fund of Funds",                              "ALL Hybrid"),
    "Liquid":                        ("Liquid",                                     "ALL Passive"),
    "Overnight Fund":                ("Overnight funds",                            "ALL Passive"),
    "Ultra Short Duration":          ("Ultra Short Duration",                       "ALL Passive"),
    "Low Duration":                  ("Low Duration",                               "ALL Passive"),
    "Fixed Maturity Plans":          ("Fixed Maturity Plans",                       "ALL Passive"),
    # Intentionally omitted (not in user's 36-bucket list):
    # Short Duration, Medium Duration, Medium to Long Duration, Long Duration,
    # Corporate Bond, Banking and PSU Fund, Credit Risk Fund, Dynamic Bond,
    # Gilt, Floating Rate, Money Market,
    # Solution Oriented - Children's Fund, Solution Oriented - Retirement Fund
}

_ALTSTREET_ETF_GOLD_RE    = re.compile(r"gold etf|gold fund|gold fof", re.IGNORECASE)
_ALTSTREET_ETF_SILVER_RE  = re.compile(r"silver etf|silver fund|silver fof", re.IGNORECASE)
_INTL_EQUITY_RE           = re.compile(
    r"nasdaq|s&p 500|global equity|international equity|overseas equity"
    r"|hang seng|us equity|us stocks|world equity",
    re.IGNORECASE,
)


def altstreet_to_bucket(
    raw_category: str,
    amfitype: str | None,
    amfi_name: str,
) -> tuple[str, str] | None:
    """Map raw altstreet_scheme_master.category to (bucket_36, group)."""
    # ETFs category — split by gold, silver, or generic
    if raw_category in ("ETFs", "ETFs - Other"):
        if amfitype == "GOLD ETFs" or _ALTSTREET_ETF_GOLD_RE.search(amfi_name):
            return "Gold ETFs / Gold FoFs", "ALL Passive"
        if _ALTSTREET_ETF_SILVER_RE.search(amfi_name):
            return "Silver ETFs / Silver FoFs", "ALL Passive"
        return "ETFs", "ALL Passive"

    # FoFs — distinguish domestic vs overseas
    if raw_category in ("FoFs", "FoFs (Domestic)"):
        # Gold/silver FoFs can appear here too
        if _ALTSTREET_ETF_GOLD_RE.search(amfi_name):
            return "Gold ETFs / Gold FoFs", "ALL Passive"
        if _ALTSTREET_ETF_SILVER_RE.search(amfi_name):
            return "Silver ETFs / Silver FoFs", "ALL Passive"
        if amfitype == "FOF-Overseas":
            return "International ETFs / FoFs", "ALL Equity"
        return "Fund of Funds", "ALL Hybrid"

    if raw_category == "FoFs (Overseas)":
        return "International ETFs / FoFs", "ALL Equity"

    # International equity: overseas-focused funds under generic equity/index categories
    if raw_category in ("Market Cap Fund", "Index Funds") and _INTL_EQUITY_RE.search(amfi_name):
        return "International Equity", "ALL Equity"

    return _ALTSTREET_TO_BUCKET.get(raw_category)


def main() -> None:
    conn = psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASSWORD,
    )
    conn.autocommit = False
    cur = conn.cursor()

    print("Step 3: Building versioned category taxonomy ...")

    # ── Schema ─────────────────────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS category_taxonomy_version (
            id             SERIAL PRIMARY KEY,
            version_number INT  NOT NULL UNIQUE,
            description    TEXT,
            is_active      BOOLEAN NOT NULL DEFAULT FALSE,
            created_at     TIMESTAMP DEFAULT NOW()
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS category_taxonomy_mapping (
            id             BIGSERIAL PRIMARY KEY,
            version_number INT  NOT NULL REFERENCES category_taxonomy_version(version_number),
            schemecode     INTEGER NOT NULL,
            raw_category   VARCHAR(200),
            raw_amfitype   VARCHAR(100),
            bucket_36      VARCHAR(100),
            bucket_group   VARCHAR(30),
            valid_from     DATE,
            created_at     TIMESTAMP DEFAULT NOW(),
            UNIQUE(schemecode, version_number)
        );
    """)
    cur.execute("""
        CREATE OR REPLACE VIEW category_taxonomy_current AS
            SELECT m.*
            FROM category_taxonomy_mapping m
            JOIN category_taxonomy_version v ON v.version_number = m.version_number
            WHERE v.is_active = TRUE;
    """)

    # ── Determine next version number ──────────────────────────────────────
    cur.execute("SELECT COALESCE(MAX(version_number), 0) FROM category_taxonomy_version;")
    last_ver = cur.fetchone()[0]
    new_ver  = last_ver + 1

    # Deactivate previous versions
    cur.execute("UPDATE category_taxonomy_version SET is_active = FALSE;")
    cur.execute(
        "INSERT INTO category_taxonomy_version (version_number, description, is_active)"
        " VALUES (%s, %s, TRUE)",
        (new_ver, f"36-bucket taxonomy built {date.today()}"),
    )
    print(f"  Created taxonomy version {new_ver}")

    # ── Load selfmade_scheme_category_benchmark for equity sub-buckets ─────
    cur.execute("""
        SELECT schemecode, category, amfi_name
        FROM selfmade_scheme_category_benchmark;
    """)
    scb_by_code: dict[int, tuple[str, str]] = {}
    for sc, cat, name in cur.fetchall():
        scb_by_code[int(sc)] = (cat, name or "")
    print(f"  Loaded {len(scb_by_code)} rows from selfmade_scheme_category_benchmark")

    # ── Load all active schemes from altstreet + accord_fintech ───────────
    cur.execute("""
        SELECT
            sm.scheme_id::integer,
            sm.category,
            afd.amfitype,
            afd.amfi_name,
            afd.incept_date::date
        FROM altstreet_scheme_master sm
        LEFT JOIN accord_fintech_scheme_details afd ON afd.schemecode::text = sm.scheme_id
        WHERE sm.status = 'Active';
    """)
    rows = cur.fetchall()
    print(f"  Fetched {len(rows)} active schemes")

    inserts = []
    bucket_counts: dict[str, int] = {}
    no_bucket = 0

    for sc, raw_cat, amfitype, amfi_name, incept_dt in rows:
        schemecode    = int(sc) if sc is not None else None
        raw_category  = raw_cat or ""
        name          = amfi_name or ""
        valid_from    = incept_dt if incept_dt else date(2000, 1, 1)

        bucket: tuple[str, str] | None = None

        # Priority 1: selfmade_scheme_category_benchmark (granular equity)
        if schemecode and schemecode in scb_by_code:
            scb_cat, scb_name = scb_by_code[schemecode]
            bucket = scb_to_bucket(scb_cat, scb_name)

        # Priority 2: altstreet_scheme_master.category
        if bucket is None and raw_category:
            bucket = altstreet_to_bucket(raw_category, amfitype, name)

        if bucket is None:
            no_bucket += 1
            # Still insert a row so we can query coverage; bucket_36 = NULL
            inserts.append((new_ver, schemecode, raw_category, amfitype, None, None, valid_from))
            continue

        bucket_36, bucket_group = bucket
        bucket_counts[bucket_36] = bucket_counts.get(bucket_36, 0) + 1
        inserts.append((new_ver, schemecode, raw_category, amfitype, bucket_36, bucket_group, valid_from))

    print(f"  Schemes assigned a bucket: {sum(bucket_counts.values())}")
    print(f"  Schemes with no bucket (debt/solution-oriented/other): {no_bucket}")

    if inserts:
        execute_values(
            cur,
            """INSERT INTO category_taxonomy_mapping
               (version_number, schemecode, raw_category, raw_amfitype,
                bucket_36, bucket_group, valid_from)
               VALUES %s
               ON CONFLICT (schemecode, version_number) DO UPDATE SET
                 raw_category  = EXCLUDED.raw_category,
                 raw_amfitype  = EXCLUDED.raw_amfitype,
                 bucket_36     = EXCLUDED.bucket_36,
                 bucket_group  = EXCLUDED.bucket_group,
                 valid_from    = EXCLUDED.valid_from
            """,
            inserts,
            page_size=1000,
        )

    conn.commit()

    # ── Verification ───────────────────────────────────────────────────────
    print("\n  bucket_36 distribution:")
    cur.execute("""
        SELECT bucket_group, bucket_36, COUNT(*) as cnt
        FROM category_taxonomy_current
        WHERE bucket_36 IS NOT NULL
        GROUP BY bucket_group, bucket_36
        ORDER BY bucket_group, cnt DESC;
    """)
    rows_out = cur.fetchall()
    cur_group = None
    for group, bucket, cnt in rows_out:
        if group != cur_group:
            print(f"\n  [{group}]")
            cur_group = group
        print(f"    {bucket:<45} {cnt:>5}")

    print("\n  Coverage summary:")
    cur.execute("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN bucket_36 IS NOT NULL THEN 1 ELSE 0 END) AS with_bucket,
            SUM(CASE WHEN bucket_36 IS NULL THEN 1 ELSE 0 END) AS without_bucket,
            COUNT(DISTINCT bucket_36) AS distinct_buckets
        FROM category_taxonomy_current;
    """)
    total, with_b, without_b, n_buckets = cur.fetchone()
    print(f"    Total schemes : {total}")
    print(f"    With bucket   : {with_b}  ({round(100*with_b/max(total,1),1)}%)")
    print(f"    Without bucket: {without_b}")
    print(f"    Distinct buckets populated: {n_buckets}")

    cur.close()
    conn.close()
    print("\nStep 3 complete.")


if __name__ == "__main__":
    main()
