"""
tri_data.py
===========
Downloads 15 years of Total Returns Index (TRI) data from niftyindices.com
for all equity benchmark indices, in 1-year chunks, and ingests each chunk
into PostgreSQL (selfmade_index_returns) immediately after it's saved.

CRASH SAFETY (the critical fix from the previous version):
  - download_one_chunk() catches EVERY exception internally and returns
    None on failure. It NEVER lets an exception escape and kill the script.
  - The browser session is health-checked before each chunk; if it's dead
    (crashed renderer, broken session), it's rebuilt automatically.
  - Selectors use MULTIPLE fallback strategies (several XPath/CSS attempts
    per element) since the exact page structure wasn't verified live.
  - Run inspect_page.py FIRST if chunks keep failing on selector errors --
    it will print the real page structure so selectors can be corrected
    with certainty instead of guesswork.

SETUP:
  pip install selenium webdriver-manager pandas psycopg2-binary python-dotenv

USAGE:
  python3 tri_data.py --headless false --only "NIFTY 50"
      Test run, visible browser, one index only.

  python3 tri_data.py
      Full run, all indices, headless.

  python3 tri_data.py --verify
      Just check what's in the DB right now.

  python3 tri_data.py --ingest-only
      Don't download anything, just ingest already-downloaded CSVs.
"""

import os
import sys
import json
import time
import shutil
import signal
import argparse
import logging
from pathlib import Path
from datetime import date, timedelta, datetime

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

DOWNLOAD_DIR  = Path("./tri_downloads_raw").resolve()
COMBINED_DIR  = Path("./tri_downloads_combined").resolve()
MANIFEST_FILE = Path("./tri_manifest.json")

DOWNLOAD_DIR.mkdir(exist_ok=True)
COMBINED_DIR.mkdir(exist_ok=True)

END_DATE   = date.today()
START_DATE = date(END_DATE.year - 15, END_DATE.month, END_DATE.day)

PAGE_LOAD_TIMEOUT   = 90
AFTER_NAV_WAIT       = 6
AFTER_TAB_CLICK_WAIT = 2
AFTER_DROPDOWN_WAIT  = 1.5
AFTER_SUBMIT_WAIT    = 4
DOWNLOAD_WAIT        = 7
BETWEEN_CHUNKS_WAIT  = 2

HISTORICAL_DATA_URL = "https://www.niftyindices.com/reports/historical-data"

INDICES = [
    ("Nifty 50 TRI",                         "Equity", "Broad Market Indices", "NIFTY 50"),
    ("Nifty 100 TRI",                        "Equity", "Broad Market Indices", "NIFTY 100"),
    ("Nifty 200 TRI",                        "Equity", "Broad Market Indices", "NIFTY 200"),
    ("Nifty 500 TRI",                        "Equity", "Broad Market Indices", "NIFTY 500"),
    ("Nifty Next 50 TRI",                    "Equity", "Broad Market Indices", "NIFTY NEXT 50"),
    ("Nifty LargeMidcap 250 TRI",            "Equity", "Broad Market Indices", "NIFTY LARGEMIDCAP 250"),
    ("Nifty Midcap 150 TRI",                 "Equity", "Broad Market Indices", "NIFTY MIDCAP 150"),
    ("Nifty Midcap 50 TRI",                  "Equity", "Broad Market Indices", "NIFTY MIDCAP 50"),
    ("Nifty Smallcap 250 TRI",               "Equity", "Broad Market Indices", "NIFTY SMALLCAP 250"),
    ("Nifty Smallcap 100 TRI",               "Equity", "Broad Market Indices", "NIFTY SMALLCAP 100"),
    ("Nifty MidSmallcap 400 TRI",            "Equity", "Broad Market Indices", "NIFTY MIDSMALLCAP 400"),
    ("Nifty Microcap 250 TRI",               "Equity", "Broad Market Indices", "NIFTY MICROCAP 250"),
    ("Nifty 500 Multicap 50:25:25 TRI",      "Equity", "Broad Market Indices", "NIFTY500 MULTICAP 50:25:25"),
    ("Nifty Financial Services TRI",         "Equity", "Sectoral Indices", "NIFTY FINANCIAL SERVICES"),
    ("Nifty IT TRI",                         "Equity", "Sectoral Indices", "NIFTY IT"),
    ("Nifty Healthcare TRI",                 "Equity", "Sectoral Indices", "NIFTY HEALTHCARE INDEX"),
    ("Nifty Pharma TRI",                     "Equity", "Sectoral Indices", "NIFTY PHARMA"),
    ("Nifty Auto TRI",                       "Equity", "Sectoral Indices", "NIFTY AUTO"),
    ("Nifty Bank TRI",                       "Equity", "Sectoral Indices", "NIFTY BANK"),
    ("Nifty FMCG TRI",                       "Equity", "Sectoral Indices", "NIFTY FMCG"),
    ("Nifty Realty TRI",                     "Equity", "Sectoral Indices", "NIFTY REALTY"),
    ("Nifty Metal TRI",                      "Equity", "Sectoral Indices", "NIFTY METAL"),
    ("Nifty Private Bank TRI",               "Equity", "Sectoral Indices", "NIFTY PRIVATE BANK"),
    ("Nifty PSU Bank TRI",                   "Equity", "Sectoral Indices", "NIFTY PSU BANK"),
    ("Nifty Media TRI",                      "Equity", "Sectoral Indices", "NIFTY MEDIA"),
    ("Nifty Infrastructure TRI",             "Equity", "Thematic Indices", "NIFTY INFRASTRUCTURE"),
    ("Nifty Energy TRI",                     "Equity", "Thematic Indices", "NIFTY ENERGY"),
    ("Nifty India Consumption TRI",          "Equity", "Thematic Indices", "NIFTY INDIA CONSUMPTION"),
    ("Nifty MNC TRI",                        "Equity", "Thematic Indices", "NIFTY MNC"),
    ("Nifty PSE TRI",                        "Equity", "Thematic Indices", "NIFTY PSE"),
    ("Nifty Commodities TRI",                "Equity", "Thematic Indices", "NIFTY COMMODITIES"),
    ("Nifty Services Sector TRI",            "Equity", "Thematic Indices", "NIFTY SERVICES SECTOR"),
    ("Nifty India Manufacturing TRI",        "Equity", "Thematic Indices", "NIFTY INDIA MANUFACTURING"),
    ("Nifty 100 ESG TRI",                    "Equity", "Thematic Indices", "NIFTY100 ESG"),
    ("Nifty 200 Momentum 30 TRI",            "Equity", "Strategy Indices", "NIFTY200 MOMENTUM 30"),
    ("Nifty 100 Low Volatility 30 TRI",      "Equity", "Strategy Indices", "NIFTY 100 LOW VOLATILITY 30"),
    ("Nifty 100 Quality 30 TRI",             "Equity", "Strategy Indices", "NIFTY100 QUALITY 30"),
    ("Nifty 50 Value 20 TRI",                "Equity", "Strategy Indices", "NIFTY50 VALUE 20"),
    ("Nifty Dividend Opportunities 50 TRI",  "Equity", "Strategy Indices", "NIFTY DIVIDEND OPPORTUNITIES 50"),
]

# ─────────────────────────────────────────────────────────────────────────────
# MANIFEST (crash-safe, atomic, fsync'd)
# ─────────────────────────────────────────────────────────────────────────────

def load_manifest() -> dict:
    if MANIFEST_FILE.exists():
        try:
            return json.loads(MANIFEST_FILE.read_text())
        except json.JSONDecodeError:
            log.warning("manifest.json corrupted, starting fresh")
            return {}
    return {}

def save_manifest(m: dict):
    tmp = MANIFEST_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(m, f, indent=2, default=str)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(MANIFEST_FILE)

def chunk_key(db_name: str, s: date, e: date) -> str:
    safe = db_name.replace(" ", "_").replace(":", "-").replace("&", "and")
    return f"{safe}__{s.isoformat()}_{e.isoformat()}"

def year_chunks(start: date, end: date):
    cur = start
    while cur < end:
        try:
            chunk_end = cur.replace(year=cur.year + 1) - timedelta(days=1)
        except ValueError:
            chunk_end = cur.replace(year=cur.year + 1, day=28) - timedelta(days=1)
        if chunk_end > end:
            chunk_end = end
        yield cur, chunk_end
        cur = chunk_end + timedelta(days=1)

def chunk_file_is_valid(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < 20:
        return False
    try:
        df = pd.read_csv(path)
        return len(df) > 0
    except Exception:
        return False

# ─────────────────────────────────────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────────────────────────────────────

def get_db_conn():
    import psycopg2
    required = ["DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD"]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        log.error("Missing required env vars: %s", missing)
        log.error("Set DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD before running.")
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
    conn.commit()

def clean_chunk_dataframe(raw_df: pd.DataFrame) -> pd.DataFrame:
    df = raw_df.copy()
    df.columns = [str(c).strip().strip('"') for c in df.columns]
    if len(df.columns) == 2:
        df.columns = ["date", "tri"]
    elif len(df.columns) >= 3:
        df = df.iloc[:, :3]
        df.columns = ["index_name", "date", "tri"]
        df = df[["date", "tri"]]
    else:
        return pd.DataFrame(columns=["date", "tri"])

    df["date"] = pd.to_datetime(
        df["date"].astype(str).str.strip().str.strip('"'),
        dayfirst=True, errors="coerce"
    )
    df["tri"] = (
        df["tri"].astype(str).str.strip().str.strip('"')
        .str.replace(",", "", regex=False)
        .pipe(pd.to_numeric, errors="coerce")
    )
    df = df.dropna(subset=["date", "tri"])
    df = df[df["tri"] > 0]
    df = df.drop_duplicates(subset=["date"]).sort_values("date")
    return df

def ingest_chunk_to_db(conn, df: pd.DataFrame, db_name: str) -> int:
    """Insert one chunk into the DB. Own transaction, own commit. Never raises."""
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
                rows, page_size=500
            )
            inserted = cur.rowcount
        conn.commit()
        return inserted
    except Exception as e:
        conn.rollback()
        log.error("  DB ingest failed for %s: %s", db_name, e)
        return -1  # signal failure distinctly from "0 inserted (all dupes)"

# ─────────────────────────────────────────────────────────────────────────────
# SELENIUM DRIVER
# ─────────────────────────────────────────────────────────────────────────────

def build_driver(headless: bool, download_dir: Path):
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from webdriver_manager.chrome import ChromeDriverManager

    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1600,1200")
    prefs = {
        "download.default_directory": str(download_dir),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
    }
    opts.add_experimental_option("prefs", prefs)

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)
    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
    return driver

def is_driver_alive(driver) -> bool:
    if driver is None:
        return False
    try:
        _ = driver.current_url
        return True
    except Exception:
        return False

# ─────────────────────────────────────────────────────────────────────────────
# PAGE INTERACTION — multi-strategy, defensive, never raises out
# ─────────────────────────────────────────────────────────────────────────────

def try_click_tab_switcher(driver, wait):
    """Try multiple strategies to find and click the tab switcher,
    then select 'Total returns Index Values'."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC

    strategies = [
        "//*[contains(text(),'Historical Index Data')]",
        "//div[contains(@class,'dropdown') and contains(.,'Historical')]",
        "//span[contains(text(),'Historical Index Data')]",
    ]
    for xpath in strategies:
        try:
            elem = wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
            elem.click()
            time.sleep(1)
            tri_strategies = [
                "//*[contains(text(),'Total returns Index Values')]",
                "//*[contains(text(),'Total Returns Index Values')]",
                "//*[contains(translate(text(),'TOTAL RETURNS','total returns'),'total returns')]",
            ]
            for tri_xpath in tri_strategies:
                try:
                    tri_elem = wait.until(EC.element_to_be_clickable((By.XPATH, tri_xpath)))
                    tri_elem.click()
                    time.sleep(AFTER_TAB_CLICK_WAIT)
                    return True
                except Exception:
                    continue
        except Exception:
            continue
    return False

def try_select_dropdowns(driver, index_type, sub_index_type, index_name):
    """Try multiple strategies for the 3 dropdowns. Returns True on success."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import Select

    # Strategy A: standard <select> elements in order
    try:
        selects = driver.find_elements(By.TAG_NAME, "select")
        if len(selects) >= 3:
            Select(selects[0]).select_by_visible_text(index_type)
            time.sleep(AFTER_DROPDOWN_WAIT)
            Select(selects[1]).select_by_visible_text(sub_index_type)
            time.sleep(AFTER_DROPDOWN_WAIT)
            Select(selects[2]).select_by_visible_text(index_name)
            time.sleep(AFTER_DROPDOWN_WAIT)
            return True
    except Exception as e:
        log.debug("  Strategy A (standard selects) failed: %s", e)

    # Strategy B: custom dropdown divs that need click-to-open then click-option
    try:
        labels = ["Select an Index Type", "Select a Sub-Index", "Select an Index"]
        values = [index_type, sub_index_type, index_name]
        for label, value in zip(labels, values):
            container = driver.find_element(
                By.XPATH, f"//*[contains(text(),'{label}')]/following::*[1]"
            )
            container.click()
            time.sleep(0.8)
            option = driver.find_element(
                By.XPATH, f"//*[normalize-space(text())='{value}']"
            )
            option.click()
            time.sleep(AFTER_DROPDOWN_WAIT)
        return True
    except Exception as e:
        log.debug("  Strategy B (custom dropdowns) failed: %s", e)

    return False

def try_set_dates(driver, from_str, to_str):
    from selenium.webdriver.common.by import By

    strategies = [
        "//input[@type='text' and (contains(@id,'date') or contains(@id,'Date'))]",
        "//input[contains(@class,'date')]",
        "//input[@placeholder and contains(translate(@placeholder,'DATE','date'),'date')]",
    ]
    for xpath in strategies:
        try:
            inputs = driver.find_elements(By.XPATH, xpath)
            if len(inputs) >= 2:
                for inp, val in zip(inputs[:2], [from_str, to_str]):
                    driver.execute_script("arguments[0].value = '';", inp)
                    inp.send_keys(val)
                    time.sleep(0.5)
                return True
        except Exception:
            continue
    return False

def try_click_submit(driver):
    from selenium.webdriver.common.by import By
    strategies = [
        "//button[contains(text(),'Submit')]",
        "//input[@value='Submit']",
        "//button[@type='submit']",
        "//*[contains(@class,'submit-btn') or contains(@id,'submit')]",
    ]
    for xpath in strategies:
        try:
            btn = driver.find_element(By.XPATH, xpath)
            btn.click()
            time.sleep(AFTER_SUBMIT_WAIT)
            return True
        except Exception:
            continue
    return False

def try_click_csv_download(driver):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    strategies = [
        "//*[contains(text(),'csv format')]",
        "//*[contains(text(),'CSV format')]",
        "//a[contains(translate(text(),'CSV','csv'),'csv')]",
    ]
    for xpath in strategies:
        try:
            link = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((By.XPATH, xpath))
            )
            link.click()
            return True
        except Exception:
            continue
    return False

# ─────────────────────────────────────────────────────────────────────────────
# DOWNLOAD ONE CHUNK — NEVER RAISES, ALWAYS RETURNS None ON FAILURE
# ─────────────────────────────────────────────────────────────────────────────

def download_one_chunk(driver, db_name, index_type, sub_index_type,
                       site_index_name, chunk_start, chunk_end):
    """
    This function is the single most important safety boundary in the
    script. No matter what goes wrong inside it -- timeouts, missing
    elements, stale references, anything -- it catches it and returns
    None. It must never let an exception escape.
    """
    from selenium.webdriver.support.ui import WebDriverWait

    try:
        wait = WebDriverWait(driver, 20)

        driver.get(HISTORICAL_DATA_URL)
        time.sleep(AFTER_NAV_WAIT)

        if not try_click_tab_switcher(driver, wait):
            log.warning("  Could not switch to TRI tab (continuing anyway, "
                       "may already be on correct tab)")

        if not try_select_dropdowns(driver, index_type, sub_index_type, site_index_name):
            log.error("  Could not select dropdowns for %s", db_name)
            return None

        from_str = chunk_start.strftime("%d-%b-%Y")
        to_str   = chunk_end.strftime("%d-%b-%Y")
        if not try_set_dates(driver, from_str, to_str):
            log.error("  Could not set date range for %s", db_name)
            return None

        if not try_click_submit(driver):
            log.error("  Could not click Submit for %s", db_name)
            return None

        files_before = set(DOWNLOAD_DIR.glob("*"))

        if not try_click_csv_download(driver):
            log.error("  Could not find csv download link for %s (%s to %s)",
                      db_name, from_str, to_str)
            return None

        time.sleep(DOWNLOAD_WAIT)
        files_after = set(DOWNLOAD_DIR.glob("*"))
        new_files = [f for f in (files_after - files_before)
                    if not f.name.endswith(".crdownload")]

        if not new_files:
            time.sleep(3)
            files_after = set(DOWNLOAD_DIR.glob("*"))
            new_files = [f for f in (files_after - files_before)
                        if not f.name.endswith(".crdownload")]

        if not new_files:
            log.warning("  No file appeared after download click for %s (%s to %s)",
                       db_name, from_str, to_str)
            return None

        return max(new_files, key=lambda f: f.stat().st_mtime)

    except Exception as e:
        # THE CRITICAL CATCH-ALL. Every possible exception from Selenium,
        # timeouts, stale elements, browser crashes -- all land here.
        log.error("  EXCEPTION during chunk download for %s (%s to %s): %s: %s",
                  db_name, chunk_start, chunk_end, type(e).__name__, e)
        return None

def rename_chunk_file(raw_path, db_name, chunk_start, chunk_end):
    key = chunk_key(db_name, chunk_start, chunk_end)
    target = DOWNLOAD_DIR / f"{key}.csv"
    if target.exists():
        target.unlink()
    shutil.move(str(raw_path), str(target))
    return target

# ─────────────────────────────────────────────────────────────────────────────
# MAIN DOWNLOAD LOOP
# ─────────────────────────────────────────────────────────────────────────────

def run_downloads(headless: bool, only_indices, recombine_every: int = 10):
    manifest = load_manifest()
    conn = get_db_conn()
    ensure_table(conn)
    log.info("DB connection established and table verified.")

    targets = INDICES
    if only_indices:
        targets = [t for t in INDICES if t[0] in only_indices or t[3] in only_indices]
        if not targets:
            log.error("No matching indices for --only: %s", only_indices)
            conn.close()
            return

    driver = build_driver(headless=headless, download_dir=DOWNLOAD_DIR)
    chunks_since_combine = 0

    total_needed = total_done = total_failed = 0
    total_db_inserted = total_db_dupes = 0
    failed_chunks_list = []

    try:
        for db_name, idx_type, sub_idx_type, site_name in targets:
            chunks = list(year_chunks(START_DATE, END_DATE))
            total_needed += len(chunks)

            log.info("=" * 70)
            log.info("INDEX: %s  (%d chunks)", db_name, len(chunks))

            for chunk_start, chunk_end in chunks:
                key = chunk_key(db_name, chunk_start, chunk_end)
                expected_file = DOWNLOAD_DIR / f"{key}.csv"

                already_done = (
                    manifest.get(key, {}).get("status") == "done"
                    and manifest.get(key, {}).get("db_ingested") is True
                    and chunk_file_is_valid(expected_file)
                )
                if already_done:
                    log.info("  [skip] %s -> %s  (already downloaded + ingested)",
                            chunk_start, chunk_end)
                    total_done += 1
                    continue

                # ── Health-check / rebuild driver if needed ─────────────────
                if not is_driver_alive(driver):
                    log.warning("  Browser session appears dead — rebuilding...")
                    try:
                        driver.quit()
                    except Exception:
                        pass
                    driver = build_driver(headless=headless, download_dir=DOWNLOAD_DIR)

                log.info("  [download] %s -> %s", chunk_start, chunk_end)

                try:
                    raw_path = download_one_chunk(
                        driver, db_name, idx_type, sub_idx_type, site_name,
                        chunk_start, chunk_end
                    )
                except Exception as e:
                    # Second layer of defense — should never trigger given
                    # download_one_chunk's internal catch-all, but kept as
                    # a hard guarantee the script cannot die here.
                    log.error("  Unexpected exception escaped download_one_chunk: %s", e)
                    raw_path = None

                if raw_path is None:
                    manifest[key] = {"status": "failed", "attempted_at": str(datetime.now())}
                    save_manifest(manifest)
                    total_failed += 1
                    failed_chunks_list.append((db_name, chunk_start, chunk_end))
                    log.warning("  FAILED: %s %s -> %s (continuing to next chunk)",
                               db_name, chunk_start, chunk_end)
                    continue

                final_path = rename_chunk_file(raw_path, db_name, chunk_start, chunk_end)

                if not chunk_file_is_valid(final_path):
                    manifest[key] = {"status": "failed_empty", "attempted_at": str(datetime.now())}
                    save_manifest(manifest)
                    total_failed += 1
                    failed_chunks_list.append((db_name, chunk_start, chunk_end))
                    log.warning("  FAILED (empty file): %s %s -> %s", db_name, chunk_start, chunk_end)
                    continue

                row_count = len(pd.read_csv(final_path))

                # ── DB ingestion — own transaction, never crashes script ────
                cleaned = clean_chunk_dataframe(pd.read_csv(final_path))
                inserted = ingest_chunk_to_db(conn, cleaned, db_name)

                if inserted == -1:
                    manifest[key] = {
                        "status": "done", "file": str(final_path), "rows": row_count,
                        "downloaded_at": str(datetime.now()),
                        "db_ingested": False, "db_error": True,
                    }
                    log.warning("  CSV saved OK but DB ingest FAILED for %s %s->%s "
                               "(re-run with --ingest-only later)",
                               db_name, chunk_start, chunk_end)
                else:
                    dupes = row_count - inserted
                    total_db_inserted += inserted
                    total_db_dupes += dupes
                    manifest[key] = {
                        "status": "done", "file": str(final_path), "rows": row_count,
                        "downloaded_at": str(datetime.now()),
                        "db_ingested": True, "db_rows_inserted": inserted,
                        "db_ingested_at": str(datetime.now()),
                    }
                    log.info("  OK -> %s (%d rows)  DB: %d inserted, %d duplicates skipped",
                            final_path.name, row_count, inserted, dupes)

                save_manifest(manifest)
                total_done += 1
                chunks_since_combine += 1

                if chunks_since_combine >= recombine_every:
                    log.info("  [checkpoint] Re-combining CSVs so far...")
                    try:
                        combine_all()
                    except Exception as e:
                        log.warning("  Checkpoint combine failed (non-fatal): %s", e)
                    chunks_since_combine = 0

                time.sleep(BETWEEN_CHUNKS_WAIT)

        log.info("=" * 70)
        log.info("SUMMARY: %d done, %d failed, %d total chunks", total_done, total_failed, total_needed)
        log.info("DB: %d rows inserted, %d duplicates skipped", total_db_inserted, total_db_dupes)
        if failed_chunks_list:
            log.warning("Failed chunks (%d) — re-run same command to retry just these:",
                       len(failed_chunks_list))
            for db_name, cs, ce in failed_chunks_list:
                log.warning("    %s : %s -> %s", db_name, cs, ce)

    finally:
        try:
            driver.quit()
        except Exception:
            pass
        conn.close()


def run_ingest_only():
    manifest = load_manifest()
    conn = get_db_conn()
    ensure_table(conn)

    pending = [k for k, v in manifest.items()
              if v.get("status") == "done" and not v.get("db_ingested")]
    log.info("Found %d chunks already downloaded but not yet ingested.", len(pending))

    total_inserted = total_dupes = 0
    for key in pending:
        v = manifest[key]
        path = Path(v["file"])
        if not chunk_file_is_valid(path):
            log.warning("  Skipping %s — file missing or invalid", key)
            continue
        db_name = key.split("__")[0].replace("_", " ")
        cleaned = clean_chunk_dataframe(pd.read_csv(path))
        inserted = ingest_chunk_to_db(conn, cleaned, db_name)
        if inserted == -1:
            log.warning("  DB ingest failed again for %s", key)
            continue
        row_count = len(pd.read_csv(path))
        dupes = row_count - inserted
        total_inserted += inserted
        total_dupes += dupes
        manifest[key]["db_ingested"] = True
        manifest[key]["db_rows_inserted"] = inserted
        manifest[key]["db_ingested_at"] = str(datetime.now())
        save_manifest(manifest)
        log.info("  %s -> %d inserted, %d duplicates", key, inserted, dupes)

    log.info("Ingest-only complete: %d rows inserted, %d duplicates skipped",
             total_inserted, total_dupes)
    conn.close()


def verify_db():
    conn = get_db_conn()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT index_name, COUNT(*) as rows, MIN(date) as from_date, MAX(date) as to_date
            FROM selfmade_index_returns
            GROUP BY index_name ORDER BY index_name
        """)
        rows = cur.fetchall()
    conn.close()
    print("\n" + "=" * 80)
    print(f"{'Index Name':<45} {'Rows':>6}  {'From':>12}  {'To':>12}")
    print("-" * 80)
    for r in rows:
        print(f"{r[0]:<45} {r[1]:>6}  {str(r[2]):>12}  {str(r[3]):>12}")
    print("=" * 80)
    print(f"Total indices: {len(rows)}")


def combine_all():
    for db_name, _, _, _ in INDICES:
        safe = db_name.replace(" ", "_").replace(":", "-").replace("&", "and")
        chunk_files = sorted(DOWNLOAD_DIR.glob(f"{safe}__*.csv"))
        if not chunk_files:
            continue
        dfs = []
        for f in chunk_files:
            try:
                raw = pd.read_csv(f)
                cleaned = clean_chunk_dataframe(raw)
                if not cleaned.empty:
                    dfs.append(cleaned)
            except Exception as e:
                log.debug("  Could not read %s: %s", f, e)
        if not dfs:
            continue
        combined = pd.concat(dfs, ignore_index=True)
        combined = combined.drop_duplicates(subset=["date"]).sort_values("date")
        combined.insert(0, "index_name", db_name)
        combined["date"] = pd.to_datetime(combined["date"]).dt.strftime("%Y-%m-%d")
        out_path = COMBINED_DIR / f"{safe}.csv"
        combined.to_csv(out_path, index=False)
        log.info("Combined %s: %d rows -> %s", db_name, len(combined), out_path)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    def handle_interrupt(signum, frame):
        log.warning("Interrupt received — all completed chunks are already "
                   "saved and in the DB. Safe to re-run later.")
        try:
            combine_all()
        except Exception:
            pass
        sys.exit(1)

    signal.signal(signal.SIGINT, handle_interrupt)
    signal.signal(signal.SIGTERM, handle_interrupt)

    parser = argparse.ArgumentParser()
    parser.add_argument("--headless", default="true", choices=["true", "false"])
    parser.add_argument("--only", nargs="+", default=None)
    parser.add_argument("--combine-only", action="store_true")
    parser.add_argument("--ingest-only", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--recombine-every", type=int, default=10)
    args = parser.parse_args()

    if args.verify:
        verify_db()
    elif args.combine_only:
        combine_all()
    elif args.ingest_only:
        run_ingest_only()
    else:
        run_downloads(headless=(args.headless == "true"), only_indices=args.only,
                      recombine_every=args.recombine_every)
        combine_all()
        log.info("Done. Run with --verify to check DB contents.")