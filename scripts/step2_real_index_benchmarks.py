"""
Step 2: Rebuild selfmade_scheme_category_benchmark against real index data.

selfmade_index_returns now holds 15 years of daily TRI for 29 benchmark
indices (4 true TRI from niftyindices.com, 25 approximated from Yahoo
Finance + dividend yield compounding — see selfmade_index_source_log).
This script re-categorises every active equity scheme, maps it to the
best available real index, and records whether that mapping is an exact
match or a fallback substitute.

Idempotent — drops and recreates the table on every run.
"""

import os
import re
from datetime import date

import psycopg2
from psycopg2.extras import execute_values

DB_HOST = os.environ.get("DB_HOST", os.environ.get("POSTGRES_HOST", "localhost"))
DB_PORT = os.environ.get("DB_PORT", os.environ.get("POSTGRES_PORT", "5432"))
DB_NAME = os.environ.get("DB_NAME", os.environ.get("POSTGRES_DB", "Altstreet_AI"))
DB_USER = os.environ.get("DB_USER", os.environ.get("POSTGRES_USER", "piyushrajlenka"))
DB_PASSWORD = os.environ.get("DB_PASSWORD", os.environ.get("POSTGRES_PASSWORD", ""))

# category -> (benchmark_index, is_fallback_benchmark)
CATEGORY_BENCHMARK_MAP = {
    "Equity — Flexi Cap":               ("Nifty 500 TRI", False),
    "Equity — Large Cap":               ("Nifty 100 TRI", False),
    "Equity — Large & Mid Cap":         ("Nifty LargeMidcap 250 TRI", False),
    "Equity — Mid Cap":                 ("Nifty Midcap 150 TRI", False),
    "Equity — Small Cap":               ("Nifty Smallcap 250 TRI", False),
    "Equity — Multi Cap":               ("Nifty 500 Multicap 50:25:25 TRI", False),
    "Equity — Focused Fund":            ("Nifty 500 TRI", False),
    "Equity — Contra Fund":             ("Nifty 500 TRI", False),
    "Equity — Value Fund":              ("Nifty 500 TRI", True),
    "Equity — Dividend Yield":          ("Nifty 500 TRI", True),
    "Equity — ELSS / Tax Saving":       ("Nifty 500 TRI", False),
    "Equity — Quant":                   ("Nifty 500 TRI", False),
    "Equity — Momentum (Active)":       ("Nifty 500 TRI", False),
    "Equity — ESG / Sustainable":       ("Nifty 100 TRI", True),
    "Equity — General / Diversified":   ("Nifty 500 TRI", False),

    "Equity Index — Nifty 50 / Sensex": ("Nifty 50 TRI", False),
    "Equity Index — Nifty Next 50 / Sensex Next": ("Nifty Next 50 TRI", False),
    "Equity Index — Nifty 100":         ("Nifty 100 TRI", False),
    "Equity Index — Multicap (Rule-based)": ("Nifty 500 Multicap 50:25:25 TRI", False),
    "Equity Index — Nifty LargeMidcap 250": ("Nifty LargeMidcap 250 TRI", False),
    "Equity Index — Nifty Midcap":      ("Nifty Midcap 150 TRI", False),
    "Equity Index — Nifty Smallcap / Microcap": ("Nifty Smallcap 250 TRI", False),
    "Equity Index — Nifty MidSmall":    ("Nifty MidSmallcap 400 TRI", False),
    "Equity Index — Nifty 500":         ("Nifty 500 TRI", False),
    "Equity Index — Nifty 200":         ("Nifty 200 TRI", False),
    "Equity Index — Equal Weight":      ("Nifty 50 TRI", True),
    "Equity Index — Momentum Factor":   ("Nifty 500 TRI", True),
    "Equity Index — Quality Factor":    ("Nifty 100 TRI", True),
    "Equity Index — Low Volatility Factor": ("Nifty 100 TRI", True),
    "Equity Index — Value Factor":      ("Nifty 500 TRI", True),
    "Equity Index — Alpha Factor":      ("Nifty 500 TRI", True),
    "Equity Index — Shariah":           ("Nifty 500 TRI", True),
    "Equity Index — BSE 1000":          ("Nifty 500 TRI", True),

    "Equity Sectoral — Banking & Financial Services": ("Nifty Financial Services TRI", False),
    "Equity Sectoral — Pharma & Healthcare":   ("Nifty Pharma TRI", True),
    "Equity Sectoral — Technology & Innovation": ("Nifty IT TRI", False),
    "Equity Sectoral — Infrastructure":        ("Nifty Infrastructure TRI", False),
    "Equity Sectoral — Consumption & FMCG":    ("Nifty FMCG TRI", False),
    "Equity Sectoral — Manufacturing":         ("Nifty 500 TRI", True),
    "Equity Sectoral — PSU":                   ("Nifty PSE TRI", False),
    "Equity Sectoral — Energy & Power":        ("Nifty Energy TRI", False),
    "Equity Sectoral — MNC":                   ("Nifty MNC TRI", False),
    "Equity Sectoral — Real Estate & Housing": ("Nifty Realty TRI", False),
    "Equity Sectoral — Auto & EV":             ("Nifty Auto TRI", False),
    "Equity Sectoral — Metals, Mining & Commodities": ("Nifty Metal TRI", False),
    "Equity Sectoral — Services":              ("Nifty Services Sector TRI", False),
    "Equity Sectoral — Entertainment & Media": ("Nifty Media TRI", False),

    "Other / Unclassified":             ("Nifty 50 TRI", True),
}

THEMATIC_DEFAULT = ("Nifty 500 TRI", False)
SECTORAL_DEFAULT = ("Nifty 500 TRI", True)
OTHER_INDEX_DEFAULT = ("Nifty 500 TRI", True)
# Absolute last resort: no category-specific or prefix-based match exists at all.
CATCH_ALL_DEFAULT = ("Nifty 50 TRI", True)

# Pre-compiled regex patterns
RE_MIDCAP = re.compile(r"\bmid\s*cap\s*fund\b")
RE_SMALLCAP = re.compile(r"\bsmall\s*cap\s*fund\b")
RE_MICROCAP = re.compile(r"\bmicro\s*cap\s*fund\b")
RE_MULTICAP = re.compile(r"\bmulti\s*cap\s*fund\b")
RE_VALUE = re.compile(r"\bvalue\s*fund\b")


EXCLUDE_KEYWORDS = [
    "liquid", "overnight", "money market", "gilt", "government securities",
    "dynamic bond", "corporate bond", "credit risk", "banking & psu",
    "banking and psu", "fixed maturity", "fmp", "interval fund",
    "capital protection", "dual advantage", "arbitrage", "equity savings",
    "balanced advantage", "balanced hybrid", "aggressive hybrid",
    "conservative hybrid", "multi asset", "asset allocation",
    "gold etf", "gold fund", "silver etf", "silver fund",
    "international", "overseas", "global", "nasdaq", "hang seng",
    "us equity", "s&p 500", "reit", "children", "retirement", "ulis",
    "fund of fund", " fof ", "sdl", "crisil ibx", "crisil-ibx", "ibx",
    "debt", "bond", "aaa ", "gsec", "g-sec",
]


def categorise(name: str) -> str | None:
    n = name.lower()

    # --- EXCLUDE non-equity ---
    for kw in EXCLUDE_KEYWORDS:
        if kw in n:
            return None

    # --- ELSS (check before other equity) ---
    elss_kw = [
        "elss", "tax saver fund", "tax saving fund", "taxshield", "tax plan",
        "tax advantage fund", "tax gain", "long term advantage fund",
        "long term equity fund", "infrastructure tax saving",
    ]
    for kw in elss_kw:
        if kw in n:
            return "Equity — ELSS / Tax Saving"

    # --- Pure equity ---
    if "flexi cap" in n or "flexicap" in n:
        return "Equity — Flexi Cap"
    if any(k in n for k in ["large & mid cap", "large and mid cap",
                            "largemidcap 250", "large midcap 250"]):
        return "Equity — Large & Mid Cap"
    if any(k in n for k in ["large cap fund", "largecap fund", "bluechip fund",
                            "blue chip fund", "top 100 fund", "top 200 fund",
                            "frontline equity", "focused large cap"]):
        return "Equity — Large Cap"
    if RE_MIDCAP.search(n) and "small" not in n:
        return "Equity — Mid Cap"
    if RE_SMALLCAP.search(n) and "mid" not in n:
        return "Equity — Small Cap"
    if RE_MICROCAP.search(n):
        return "Equity — Small Cap"
    if RE_MULTICAP.search(n) and "nifty" not in n:
        return "Equity — Multi Cap"
    if any(k in n for k in ["focused fund", "focused equity fund",
                            "focussed equity fund", "focus fund"]):
        return "Equity — Focused Fund"
    if "contra fund" in n:
        return "Equity — Contra Fund"
    if RE_VALUE.search(n):
        return "Equity — Value Fund"
    if "dividend yield fund" in n:
        return "Equity — Dividend Yield"
    if any(k in n for k in ["quant fund", "quant equity fund"]):
        return "Equity — Quant"
    if any(k in n for k in ["momentum fund", "active momentum fund"]):
        return "Equity — Momentum (Active)"
    if "esg" in n:
        return "Equity — ESG / Sustainable"

    # --- Thematic ---
    if "business cycle fund" in n:
        return "Equity Thematic — Business Cycle"
    if "conglomerate fund" in n:
        return "Equity Thematic — Conglomerate"
    if any(k in n for k in ["special opportunities fund", "special situations fund"]):
        return "Equity Thematic — Special Situations"
    if any(k in n for k in ["india opportunities fund", "opportunities fund",
                            "emerging leaders fund", "emerging bluechip fund",
                            "resurgent india fund", "india reforms fund",
                            "emerging equities fund"]):
        return "Equity Thematic — India Opportunities"

    # --- Sectoral ---
    if any(k in n for k in ["banking & financial services fund",
                            "financial services fund", "nifty bank etf",
                            "bank index fund", "nifty private bank",
                            "nifty psu bank"]):
        return "Equity Sectoral — Banking & Financial Services"
    if any(k in n for k in ["pharma fund", "healthcare fund", "health care fund",
                            "pharma & healthcare", "nifty healthcare",
                            "nifty pharma"]):
        return "Equity Sectoral — Pharma & Healthcare"
    if any(k in n for k in ["technology fund", "tech fund", "digital india fund",
                            "innovation fund", "nifty it etf",
                            "nifty it index fund"]):
        return "Equity Sectoral — Technology & Innovation"
    if any(k in n for k in ["infrastructure fund", "infra fund",
                            "nifty infrastructure", "power & infra fund"]):
        return "Equity Sectoral — Infrastructure"
    if any(k in n for k in ["consumption fund", "fmcg fund", "consumer fund",
                            "nifty india consumption", "nifty fmcg"]):
        return "Equity Sectoral — Consumption & FMCG"
    if any(k in n for k in ["manufacturing fund", "nifty india manufacturing"]):
        return "Equity Sectoral — Manufacturing"
    if any(k in n for k in ["psu equity fund", "psu fund", "nifty pse etf",
                            "nifty cpse etf"]):
        return "Equity Sectoral — PSU"
    if any(k in n for k in ["energy fund", "resources & energy fund",
                            "power etf", "nifty energy"]):
        return "Equity Sectoral — Energy & Power"
    if "transportation and logistics fund" in n:
        return "Equity Sectoral — Transportation & Logistics"
    if any(k in n for k in ["mnc fund", "nifty mnc etf"]):
        return "Equity Sectoral — MNC"
    if any(k in n for k in ["real estate securities fund", "realty etf",
                            "nifty realty", "bse housing"]):
        return "Equity Sectoral — Real Estate & Housing"
    if any(k in n for k in ["auto fund", "auto etf", "nifty auto", "nifty ev"]):
        return "Equity Sectoral — Auto & EV"
    if any(k in n for k in ["defence fund", "defence etf", "india defence"]):
        return "Equity Sectoral — Defence"
    if any(k in n for k in ["commodity equities fund", "commodities fund",
                            "commodities index fund", "commodities etf",
                            "nifty commodities"]):
        return "Equity Sectoral — Metals, Mining & Commodities"
    if any(k in n for k in ["services opportunities fund", "services fund",
                            "exports & services fund", "exports and services fund"]):
        return "Equity Sectoral — Services"
    if any(k in n for k in ["internet etf", "india internet etf"]):
        return "Equity Sectoral — Internet & Digital"
    if any(k in n for k in ["capital market etf", "nifty capital market"]):
        return "Equity Sectoral — Capital Markets"
    if "india tourism etf" in n:
        return "Equity Sectoral — Tourism"
    if "india railways psu etf" in n:
        return "Equity Sectoral — Railways"
    if any(k in n for k in ["entertainment opportunities fund", "nifty media"]):
        return "Equity Sectoral — Entertainment & Media"

    # --- Index funds/ETFs ---
    if any(k in n for k in ["nifty 50 etf", "nifty50 etf",
                            "nifty 50 index fund", "sensex etf",
                            "sensex index fund", "nifty bees"]):
        return "Equity Index — Nifty 50 / Sensex"
    if any(k in n for k in ["nifty next 50", "nifty junior bees",
                            "bse sensex next"]):
        return "Equity Index — Nifty Next 50 / Sensex Next"
    if any(k in n for k in ["largemidcap 250 index fund", "largemidcap 250 etf",
                            "large midcap 250 index fund"]):
        return "Equity Index — Nifty LargeMidcap 250"
    if any(k in n for k in ["nifty midcap 150 etf", "nifty midcap 150 index fund",
                            "nifty midcap 100 etf"]):
        return "Equity Index — Nifty Midcap"
    if any(k in n for k in ["nifty smallcap 250 etf", "nifty smallcap 250 index fund",
                            "nifty microcap 250"]):
        return "Equity Index — Nifty Smallcap / Microcap"
    if any(k in n for k in ["nifty midsmallcap 400", "midsmallcap 400 index fund"]):
        return "Equity Index — Nifty MidSmall"
    if any(k in n for k in ["nifty 100 etf", "nifty 100 index fund"]):
        return "Equity Index — Nifty 100"
    if any(k in n for k in ["nifty 500 etf", "nifty 500 index fund",
                            "bse 500 etf", "cnx 500 fund"]):
        return "Equity Index — Nifty 500"
    if any(k in n for k in ["nifty 200 etf", "nifty 200 index fund"]):
        return "Equity Index — Nifty 200"
    if any(k in n for k in ["nifty500 multicap", "nifty 500 multicap"]):
        return "Equity Index — Multicap (Rule-based)"
    if "equal weight" in n:
        return "Equity Index — Equal Weight"
    if any(k in n for k in ["momentum 30 etf", "momentum 30 index fund",
                            "momentum 50 etf", "midcap150 momentum"]):
        return "Equity Index — Momentum Factor"
    if any(k in n for k in ["quality 30 etf", "quality 30 index fund",
                            "nifty100 quality 30", "bse quality etf"]):
        return "Equity Index — Quality Factor"
    if any(k in n for k in ["low volatility 30 etf", "low volatility 30 index fund",
                            "bse low volatility etf"]):
        return "Equity Index — Low Volatility Factor"
    if any(k in n for k in ["value 20 etf", "value 20 index fund",
                            "nifty500 value 50", "bse enhanced value"]):
        return "Equity Index — Value Factor"
    if any(k in n for k in ["nifty alpha 50 etf", "nifty200 alpha 30"]):
        return "Equity Index — Alpha Factor"
    if "shariah" in n:
        return "Equity Index — Shariah"
    if "bse 1000 index fund" in n:
        return "Equity Index — BSE 1000"

    # --- Catch-all ---
    if any(k in n for k in ["equity fund", "diversified equity"]):
        return "Equity — General / Diversified"

    # Domestic equity index funds/ETFs (factor, smart-beta, sector-leader,
    # thematic-index variants, etc.) that don't match a specific pattern
    # above still get a category — and a Nifty 50 TRI fallback benchmark
    # via get_benchmark() — instead of silently dropping out of the table.
    if "index fund" in n or "etf" in n:
        return "Other / Unclassified"

    return None


def get_benchmark(category: str) -> tuple[str, bool]:
    if category in CATEGORY_BENCHMARK_MAP:
        return CATEGORY_BENCHMARK_MAP[category]
    if category.startswith("Equity Thematic"):
        return THEMATIC_DEFAULT
    if category.startswith("Equity Sectoral"):
        return SECTORAL_DEFAULT
    if category.startswith("Equity Index"):
        return OTHER_INDEX_DEFAULT
    # Any category categorise() returns that isn't an explicit map key and
    # doesn't match a known prefix (i.e. genuinely no defensible benchmark).
    return CATCH_ALL_DEFAULT


def main():
    conn = psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASSWORD,
    )
    conn.autocommit = False
    cur = conn.cursor()

    print("Step 2: Creating selfmade_scheme_category_benchmark (real-index schema) ...")

    cur.execute("DROP TABLE IF EXISTS selfmade_scheme_category_benchmark CASCADE;")
    cur.execute("""
        CREATE TABLE selfmade_scheme_category_benchmark (
            id                    BIGSERIAL PRIMARY KEY,
            schemecode            INTEGER       NOT NULL UNIQUE,
            amc_code              INTEGER,
            amfi_name             VARCHAR(500)  NOT NULL,
            category              VARCHAR(200)  NOT NULL,
            benchmark_index       VARCHAR(300)  NOT NULL,
            is_fallback_benchmark BOOLEAN       NOT NULL DEFAULT FALSE,
            benchmark_is_true_tri BOOLEAN       NOT NULL DEFAULT FALSE,
            valid_from            DATE,
            created_at            TIMESTAMP DEFAULT NOW()
        );
    """)

    # True-TRI lookup from the source log (29 confirmed real indices)
    cur.execute("SELECT index_name, is_true_tri FROM selfmade_index_source_log;")
    true_tri_by_index = dict(cur.fetchall())

    cur.execute("""
        SELECT schemecode, amc_code, amfi_name, incept_date
        FROM accord_fintech_scheme_details
        WHERE status = 'Active'
          AND amfi_name IS NOT NULL
        ORDER BY schemecode;
    """)
    rows = cur.fetchall()
    print(f"  Fetched {len(rows)} active schemes from accord_fintech_scheme_details")

    inserts = []
    skipped = 0
    for i, (sc, amc, name, incept_date) in enumerate(rows):
        cat = categorise(name)
        if cat is None:
            skipped += 1
            continue
        bm, fallback = get_benchmark(cat)
        is_true_tri = true_tri_by_index.get(bm, False)
        valid_from = incept_date.date() if incept_date else date(2000, 1, 1)
        inserts.append((sc, amc, name, cat, bm, fallback, is_true_tri, valid_from))
        if (i + 1) % 500 == 0:
            print(f"  Processed {i + 1}/{len(rows)} schemes ...")

    print(f"  Categorised {len(inserts)} equity schemes, skipped {skipped} non-equity")

    if inserts:
        execute_values(
            cur,
            """INSERT INTO selfmade_scheme_category_benchmark
               (schemecode, amc_code, amfi_name, category, benchmark_index,
                is_fallback_benchmark, benchmark_is_true_tri, valid_from)
               VALUES %s
               ON CONFLICT (schemecode) DO UPDATE SET
                 amc_code = EXCLUDED.amc_code,
                 amfi_name = EXCLUDED.amfi_name,
                 category = EXCLUDED.category,
                 benchmark_index = EXCLUDED.benchmark_index,
                 is_fallback_benchmark = EXCLUDED.is_fallback_benchmark,
                 benchmark_is_true_tri = EXCLUDED.benchmark_is_true_tri,
                 valid_from = EXCLUDED.valid_from""",
            inserts,
            page_size=1000,
        )

    conn.commit()

    cur.execute("""
        SELECT category, benchmark_index, benchmark_is_true_tri,
               is_fallback_benchmark, COUNT(*) as funds
        FROM selfmade_scheme_category_benchmark
        GROUP BY category, benchmark_index, benchmark_is_true_tri, is_fallback_benchmark
        ORDER BY COUNT(*) DESC;
    """)
    print("\n  category | benchmark_index | true_tri | fallback | funds")
    print("  " + "-" * 110)
    for row in cur.fetchall():
        print(f"  {row[0]:<48} {row[1]:<34} {str(row[2]):>5} {str(row[3]):>9} {row[4]:>6}")

    cur.execute("""
        SELECT
          COUNT(*) as total_funds,
          SUM(CASE WHEN is_fallback_benchmark THEN 1 ELSE 0 END) as using_fallback,
          SUM(CASE WHEN benchmark_is_true_tri THEN 1 ELSE 0 END) as using_true_tri,
          ROUND(100.0 * SUM(CASE WHEN NOT is_fallback_benchmark THEN 1 ELSE 0 END) / COUNT(*), 1) as pct_exact_match
        FROM selfmade_scheme_category_benchmark;
    """)
    total, fallback, true_tri, pct = cur.fetchone()
    print(f"\n  total_funds={total}  using_fallback={fallback}  using_true_tri={true_tri}  pct_exact_match={pct}%")

    cur.close()
    conn.close()
    print("\nStep 2 complete.")


if __name__ == "__main__":
    main()
