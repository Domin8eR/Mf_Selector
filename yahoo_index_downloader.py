"""
yahoo_index_downloader.py
==========================
Downloads 15 years of price-return index data from Yahoo Finance for the
equity benchmark indices used in the AltStreet MF analytics POC, then
converts each series to an approximate Total Returns Index (TRI) by
adding back an estimated dividend yield, and ingests into Postgres
(selfmade_index_returns).

RATE LIMITING FIX (this version):
Yahoo Finance throttles sessions making many requests in a short window.
Indices that genuinely exist can fail transiently mid-run. This version:
  - Retries each ticker up to 3 times with exponential backoff when the
    failure looks like a rate-limit/timeout issue.
  - Raises delay between indices from 1.0s to 2.5s.
  - Takes a 20s cooldown every 10 indices.
  - Treats "not_found" status as retryable on next run (not permanent),
    since it may have been a rate-limit false negative.

SETUP:
  pip install yfinance pandas psycopg2-binary python-dotenv

USAGE:
  python3 yahoo_index_downloader.py --check-only
  python3 yahoo_index_downloader.py
  python3 yahoo_index_downloader.py --verify
  python3 yahoo_index_downloader.py --only "Nifty 50 TRI" "Nifty Bank TRI"

ENV / .env LOADING:
  Loads Mf_Selector/backend/.env automatically (relative to this file's
  location, not cwd).
"""

import os
import sys
import json
import time
import argparse
import logging
from pathlib import Path
from datetime import date, datetime, timedelta

import pandas as pd
from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parent / "backend" / ".env"
load_dotenv(ENV_PATH)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

if ENV_PATH.exists():
    log.info("Loaded environment from %s", ENV_PATH)
else:
    log.warning("No .env found at %s -- falling back to shell environment", ENV_PATH)

OUTPUT_DIR    = Path("./yahoo_index_data").resolve()
MANIFEST_FILE = Path("./yahoo_manifest.json")

OUTPUT_DIR.mkdir(exist_ok=True)

END_DATE   = date.today()
START_DATE = date(END_DATE.year - 15, END_DATE.month, END_DATE.day)

BETWEEN_REQUESTS_WAIT    = 2.5
COOLDOWN_EVERY_N_INDICES = 10
COOLDOWN_SECONDS         = 20

INDEX_TICKERS = {
    "Nifty 50 TRI":                         ["^NSEI"],
    "Nifty 100 TRI":                        ["^CNX100", "NIFTY100.NS"],
    "Nifty 200 TRI":                        ["^CNX200", "NIFTY200.NS"],
    "Nifty 500 TRI":                        ["^CRSLDX", "NIFTY500.NS"],
    "Nifty Next 50 TRI":                    ["^NSMIDCP", "NIFTYJR.NS"],
    "Nifty LargeMidcap 250 TRI":            ["NIFTY_LARGEMID250.NS", "NIFTYLARGEMID250.NS"],
    "Nifty Midcap 150 TRI":                 ["NIFTYMIDCAP150.NS"],
    "Nifty Midcap 50 TRI":                  ["^NSEMDCP50"],
    "Nifty Smallcap 250 TRI":               ["NIFTYSMLCAP250.NS"],
    "Nifty Smallcap 100 TRI":               ["^CNXSC", "NIFTYSMLCAP100.NS"],
    "Nifty MidSmallcap 400 TRI":            ["NIFTYMIDSML400.NS"],
    "Nifty Microcap 250 TRI":               ["NIFTY_MICROCAP250.NS", "NIFTYMICROCAP250.NS"],
    "Nifty 500 Multicap 50:25:25 TRI":      ["NIFTY500MULTICAP.NS", "NIFTY500MULTICAP502525.NS",
                                              "NIFTY500MULTICAP5025.NS", "NIFTY500MULTICAP50.NS"],
    "Nifty Financial Services TRI":         ["NIFTY_FIN_SERVICE.NS", "^CNXFIN"],
    "Nifty IT TRI":                         ["^CNXIT"],
    "Nifty Healthcare TRI":                 ["NIFTY_HEALTHCARE.NS"],
    "Nifty Pharma TRI":                     ["^CNXPHARMA"],
    "Nifty Auto TRI":                       ["^CNXAUTO"],
    "Nifty Bank TRI":                       ["^NSEBANK"],
    "Nifty FMCG TRI":                       ["^CNXFMCG"],
    "Nifty Realty TRI":                     ["^CNXREALTY"],
    "Nifty Metal TRI":                      ["^CNXMETAL"],
    "Nifty Private Bank TRI":               ["NIFTY_PVT_BANK.NS"],
    "Nifty PSU Bank TRI":                   ["^CNXPSUBANK"],
    "Nifty Media TRI":                      ["^CNXMEDIA"],
    "Nifty Infrastructure TRI":             ["^CNXINFRA"],
    "Nifty Energy TRI":                     ["^CNXENERGY"],
    "Nifty India Consumption TRI":          ["^CNXCONSUM"],
    "Nifty MNC TRI":                        ["^CNXMNC"],
    "Nifty PSE TRI":                        ["^CNXPSE"],
    "Nifty Commodities TRI":                ["^CNXCMDT"],
    "Nifty Services Sector TRI":            ["^CNXSERVICE"],
    "Nifty India Manufacturing TRI":        ["NIFTY_INDIA_MFG.NS"],
    "Nifty 100 ESG TRI":                    ["NIFTY100_ESG.NS"],
    "Nifty 200 Momentum 30 TRI":            ["NIFTY200MOMENTM30.NS"],
    "Nifty 100 Low Volatility 30 TRI":      ["NIFTY100LOWVOL30.NS"],
    "Nifty 100 Quality 30 TRI":             ["NIFTYQUALITY30.NS"],
    "Nifty 50 Value 20 TRI":                ["NIFTY50VALUE20.NS", "NIFTYVALUE20.NS",
                                              "NIFTY_VALUE20.NS"],
    "Nifty Dividend Opportunities 50 TRI":  ["NIFTYDIVOPPS50.NS", "NIFTYDIVOPP50.NS",
                                              "NIFTY_DIV_OPP_50.NS", "NIFTYDIVIDEND50.NS"],
}

DIVIDEND_YIELD_MAP = {
    "Nifty 50 TRI":                         0.013,
    "Nifty 100 TRI":                        0.013,
    "Nifty 200 TRI":                        0.013,
    "Nifty 500 TRI":                        0.012,
    "Nifty Next 50 TRI":                    0.011,
    "Nifty LargeMidcap 250 TRI":            0.011,
    "Nifty Midcap 150 TRI":                 0.009,
    "Nifty Midcap 50 TRI":                  0.009,
    "Nifty Smallcap 250 TRI":               0.007,
    "Nifty Smallcap 100 TRI":               0.007,
    "Nifty MidSmallcap 400 TRI":            0.008,
    "Nifty Microcap 250 TRI":               0.006,
    "Nifty 500 Multicap 50:25:25 TRI":      0.011,
    "Nifty Financial Services TRI":         0.008,
    "Nifty IT TRI":                         0.018,
    "Nifty Healthcare TRI":                 0.007,
    "Nifty Pharma TRI":                     0.007,
    "Nifty Auto TRI":                       0.010,
    "Nifty Bank TRI":                       0.006,
    "Nifty FMCG TRI":                       0.015,
    "Nifty Realty TRI":                     0.005,
    "Nifty Metal TRI":                      0.020,
    "Nifty Private Bank TRI":               0.005,
    "Nifty PSU Bank TRI":                   0.015,
    "Nifty Media TRI":                      0.008,
    "Nifty Infrastructure TRI":             0.012,
    "Nifty Energy TRI":                     0.022,
    "Nifty India Consumption TRI":          0.013,
    "Nifty MNC TRI":                        0.014,
    "Nifty PSE TRI":                        0.025,
    "Nifty Commodities TRI":                0.018,
    "Nifty Services Sector TRI":            0.012,
    "Nifty India Manufacturing TRI":        0.011,
    "Nifty 100 ESG TRI":                    0.013,
    "Nifty 200 Momentum 30 TRI":            0.011,
    "Nifty 100 Low Volatility 30 TRI":      0.013,
    "Nifty 100 Quality 30 TRI":             0.013,
    "Nifty 50 Value 20 TRI":                0.014,
    "Nifty Dividend Opportunities 50 TRI":  0.025,
}
DEFAULT_DIVIDEND_YIELD = 0.012


def load_manifest() -> dict:
    if MANIFEST_FILE.exists():
        try:
            return json.loads(MANIFEST_FILE.read_text())
        except json.JSONDecodeError:
            return {}
    return {}

def save_manifest(m: dict):
    tmp = MANIFEST_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(m, f, indent=2, default=str)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(MANIFEST_FILE)

def safe_filename(db_name: str) -> str:
    return db_name.replace(" ", "_").replace(":", "-").replace("&", "and")


def fetch_index_history(db_name, tickers, max_retries=3):
    import yfinance as yf

    for ticker in tickers:
        for attempt in range(1, max_retries + 1):
            try:
                tk = yf.Ticker(ticker)
                hist = tk.history(
                    start=START_DATE.isoformat(),
                    end=(END_DATE + timedelta(days=1)).isoformat(),
                    auto_adjust=False,
                )
                if hist is None or hist.empty:
                
                    if attempt < max_retries:
                        wait = 2 ** attempt
                        log.debug("  %s empty on attempt %d, retrying in %ds", ticker, attempt, wait)
                        time.sleep(wait)
                        continue
                    break
                if "Close" not in hist.columns:
                    break

                df = hist.reset_index()[["Date", "Close"]].copy()
                df.columns = ["date", "close"]
                df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
                df = df.dropna(subset=["close"])
                df = df[df["close"] > 0]

                if len(df) < 30:
                    break

                return ticker, df

            except Exception as e:
                err_str = str(e).lower()
                is_rate_limit = any(s in err_str for s in
                                    ["429", "too many requests", "rate limit", "timeout"])
                if is_rate_limit and attempt < max_retries:
                    wait = 3 * (2 ** attempt)
                    log.warning("  %s rate-limited (attempt %d/%d), waiting %ds...",
                              ticker, attempt, max_retries, wait)
                    time.sleep(wait)
                    continue
                log.debug("  Ticker %s failed for %s: %s", ticker, db_name, e)
                break

    return None, None


def run_check_only(only_indices=None):
    targets = INDEX_TICKERS
    if only_indices:
        targets = {k: v for k, v in INDEX_TICKERS.items() if k in only_indices}

    log.info("Checking %d indices against Yahoo Finance (5-day sample)...", len(targets))
    log.info("=" * 80)

    found, not_found = [], []

    for db_name, tickers in targets.items():
        try:
            import yfinance as yf
            hit = None
            for t in tickers:
                tk = yf.Ticker(t)
                h = tk.history(period="5d")
                if h is not None and not h.empty:
                    hit = (t, len(h))
                    break
            if hit:
                found.append((db_name, hit[0]))
                log.info("  FOUND      %-42s -> ticker %s", db_name, hit[0])
            else:
                not_found.append(db_name)
                log.warning("  NOT FOUND  %-42s -> tried %s", db_name, tickers)
        except Exception as e:
            not_found.append(db_name)
            log.warning("  ERROR      %-42s -> %s", db_name, e)
        time.sleep(BETWEEN_REQUESTS_WAIT)

    log.info("=" * 80)
    log.info("RESULT: %d / %d indices found on Yahoo Finance", len(found), len(targets))
    if not_found:
        log.warning("NOT available on Yahoo (will need another source for these):")
        for name in not_found:
            log.warning("    - %s", name)

    check_results = {
        "checked_at": str(datetime.now()),
        "found": [n for n, _ in found],
        "not_found": not_found,
    }
    Path("./yahoo_check_results.json").write_text(json.dumps(check_results, indent=2))
    log.info("Saved results to yahoo_check_results.json")


def apply_tri_adjustment(price_df, annual_dividend_yield):
    df = price_df.copy().sort_values("date").reset_index(drop=True)
    start_date = df["date"].iloc[0]
    df["years_elapsed"] = (df["date"] - start_date).dt.days / 365.25
    df["tri"] = df["close"] * ((1 + annual_dividend_yield) ** df["years_elapsed"])
    return df[["date", "tri"]]


def get_db_conn():
    import psycopg2
    required = ["DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD"]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        log.error("Missing required env vars: %s", missing)
        sys.exit(1)
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", 5432)),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )

def ensure_table(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS selfmade_index_returns (
                id BIGSERIAL,
                index_name VARCHAR(255) NOT NULL,
                date DATE NOT NULL,
                tri DOUBLE PRECISION NOT NULL,
                PRIMARY KEY (index_name, date)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS selfmade_index_source_log (
                index_name VARCHAR(255) PRIMARY KEY,
                source VARCHAR(50) NOT NULL,
                yahoo_ticker VARCHAR(50),
                assumed_dividend_yield DOUBLE PRECISION,
                is_true_tri BOOLEAN NOT NULL DEFAULT FALSE,
                rows_loaded INTEGER,
                from_date DATE,
                to_date DATE,
                loaded_at TIMESTAMP DEFAULT NOW()
            )
        """)
    conn.commit()

def ingest_to_db(conn, df, db_name):
    import psycopg2.extras
    if df.empty:
        return 0
    rows = [(db_name, d.strftime("%Y-%m-%d"), float(t))
            for d, t in zip(df["date"], df["tri"])]
    try:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                "INSERT INTO selfmade_index_returns (index_name, date, tri) "
                "VALUES %s ON CONFLICT (index_name, date) DO NOTHING",
                rows, page_size=1000
            )
            inserted = cur.rowcount
        conn.commit()
        return inserted
    except Exception as e:
        conn.rollback()
        log.error("  DB ingest failed for %s: %s", db_name, e)
        return -1

def log_source(conn, db_name, ticker, dividend_yield, row_count, from_date, to_date):
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO selfmade_index_source_log
                    (index_name, source, yahoo_ticker, assumed_dividend_yield,
                     is_true_tri, rows_loaded, from_date, to_date, loaded_at)
                VALUES (%s, 'yahoo_finance_tri_approx', %s, %s, FALSE, %s, %s, %s, NOW())
                ON CONFLICT (index_name) DO UPDATE SET
                    source = EXCLUDED.source,
                    yahoo_ticker = EXCLUDED.yahoo_ticker,
                    assumed_dividend_yield = EXCLUDED.assumed_dividend_yield,
                    rows_loaded = EXCLUDED.rows_loaded,
                    from_date = EXCLUDED.from_date,
                    to_date = EXCLUDED.to_date,
                    loaded_at = NOW()
            """, (db_name, ticker, dividend_yield, row_count, from_date, to_date))
        conn.commit()
    except Exception as e:
        conn.rollback()
        log.warning("  Could not log source metadata for %s: %s", db_name, e)

def verify_db():
    conn = get_db_conn()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT ir.index_name, COUNT(*) as rows,
                   MIN(ir.date) as from_date, MAX(ir.date) as to_date,
                   sl.source, sl.is_true_tri, sl.assumed_dividend_yield
            FROM selfmade_index_returns ir
            LEFT JOIN selfmade_index_source_log sl ON sl.index_name = ir.index_name
            GROUP BY ir.index_name, sl.source, sl.is_true_tri, sl.assumed_dividend_yield
            ORDER BY ir.index_name
        """)
        rows = cur.fetchall()
    conn.close()
    print("\n" + "=" * 110)
    print(f"{'Index Name':<42} {'Rows':>6}  {'From':>12}  {'To':>12}  {'Source':<24} {'TRI?':<6} {'DivYld':>7}")
    print("-" * 110)
    for r in rows:
        name, n, fd, td, src, is_tri, dy = r
        src = src or "unknown"
        tri_flag = "true" if is_tri else "approx"
        dy_str = f"{dy*100:.2f}%" if dy is not None else "-"
        print(f"{name:<42} {n:>6}  {str(fd):>12}  {str(td):>12}  {src:<24} {tri_flag:<6} {dy_str:>7}")
    print("=" * 110)
    print(f"Total indices: {len(rows)}")


def run_full(only_indices=None):
    manifest = load_manifest()
    conn = get_db_conn()
    ensure_table(conn)
    log.info("DB connection established, tables verified.")

    targets = INDEX_TICKERS
    if only_indices:
        targets = {k: v for k, v in INDEX_TICKERS.items() if k in only_indices}

    total = len(targets)
    found_count = not_found_count = db_failed_count = 0
    total_rows_inserted = 0
    not_found_list = []

    try:
        for i, (db_name, tickers) in enumerate(targets.items(), 1):
            log.info("=" * 70)
            log.info("[%d/%d] %s", i, total, db_name)

            prev = manifest.get(db_name, {})
            already_done = prev.get("status") == "done"
            if already_done:
                log.info("  [skip] already downloaded and ingested")
                found_count += 1
                total_rows_inserted += prev.get("db_rows_inserted", 0)
                continue

            if prev.get("status") == "not_found":
                log.info("  [retry] previously not_found -- retrying "
                        "(may have been rate-limited, not actually missing)")

            if i > 1 and (i - 1) % COOLDOWN_EVERY_N_INDICES == 0:
                log.info("  [cooldown] Pausing %ds after %d indices to avoid rate limiting...",
                        COOLDOWN_SECONDS, i - 1)
                time.sleep(COOLDOWN_SECONDS)

            try:
                ticker, price_df = fetch_index_history(db_name, tickers)
            except Exception as e:
                log.error("  Unexpected error fetching %s: %s", db_name, e)
                ticker, price_df = None, None

            if ticker is None:
                log.warning("  NOT FOUND on Yahoo Finance (tried %s)", tickers)
                manifest[db_name] = {
                    "status": "not_found",
                    "tried_tickers": tickers,
                    "checked_at": str(datetime.now()),
                }
                save_manifest(manifest)
                not_found_count += 1
                not_found_list.append(db_name)
                continue

            log.info("  Found via ticker %s -- %d raw price points", ticker, len(price_df))

            raw_path = OUTPUT_DIR / f"{safe_filename(db_name)}_price_return.csv"
            price_df.to_csv(raw_path, index=False)
            log.info("  Saved raw price-return CSV -> %s", raw_path.name)

            div_yield = DIVIDEND_YIELD_MAP.get(db_name, DEFAULT_DIVIDEND_YIELD)
            tri_df = apply_tri_adjustment(price_df, div_yield)

            tri_path = OUTPUT_DIR / f"{safe_filename(db_name)}_tri_approx.csv"
            tri_out = tri_df.copy()
            tri_out.insert(0, "index_name", db_name)
            tri_out["date"] = tri_out["date"].dt.strftime("%Y-%m-%d")
            tri_out.to_csv(tri_path, index=False)
            log.info("  Applied TRI approx (div yield %.2f%%) -> %s",
                    div_yield * 100, tri_path.name)

            inserted = ingest_to_db(conn, tri_df, db_name)

            if inserted == -1:
                manifest[db_name] = {
                    "status": "downloaded_db_failed",
                    "ticker": ticker,
                    "rows": len(tri_df),
                    "downloaded_at": str(datetime.now()),
                }
                save_manifest(manifest)
                db_failed_count += 1
                log.warning("  CSV saved OK but DB ingest FAILED for %s", db_name)
                continue

            dupes = len(tri_df) - inserted
            total_rows_inserted += inserted

            log_source(conn, db_name, ticker, div_yield, len(tri_df),
                      tri_df["date"].min().date(), tri_df["date"].max().date())

            manifest[db_name] = {
                "status": "done",
                "ticker": ticker,
                "rows": len(tri_df),
                "db_rows_inserted": inserted,
                "db_duplicates_skipped": dupes,
                "dividend_yield_used": div_yield,
                "downloaded_at": str(datetime.now()),
            }
            save_manifest(manifest)
            found_count += 1
            log.info("  DB: %d inserted, %d duplicates skipped", inserted, dupes)

            time.sleep(BETWEEN_REQUESTS_WAIT)

        log.info("=" * 70)
        log.info("SUMMARY: %d found+ingested, %d not found on Yahoo, %d DB failures",
                 found_count, not_found_count, db_failed_count)
        log.info("Total rows inserted this run: %d", total_rows_inserted)
        if not_found_list:
            log.warning("Indices NOT found this run (%d) -- could be genuinely missing OR "
                       "rate-limited; just re-run the script again to retry these:",
                       len(not_found_list))
            for n in not_found_list:
                log.warning("    - %s", n)

    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download approx-TRI index data from Yahoo Finance")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--only", nargs="+", default=None)
    args = parser.parse_args()

    if args.verify:
        verify_db()
    elif args.check_only:
        run_check_only(only_indices=args.only)
    else:
        run_full(only_indices=args.only)