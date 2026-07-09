"""
seed_synthetic.py — generate fake NAV data for local development.

Produces plausible-looking NAV series for a small set of synthetic funds
and a benchmark. Output is written to CSV files that can be loaded into
the staging tables once the schema exists (milestone 2+).

Rules honoured:
- Trading days only (Mon–Fri, no Indian public holidays stub)
- No weekend rows
- No forward-filled NAVs — each row is a genuine simulated value
- Start date: 2017-01-01

Usage:
    python scripts/seed_synthetic.py [--out-dir ./data/synthetic]
"""

import argparse
import csv
import os
import random
from datetime import date, timedelta

FUNDS = [
    {"id": "HDFC-LC-GROWTH", "name": "HDFC Large Cap Fund - Growth", "category": "Large Cap"},
    {"id": "SBI-BC-GROWTH", "name": "SBI Bluechip Fund - Growth", "category": "Large Cap"},
    {"id": "AXIS-BC-GROWTH", "name": "Axis Bluechip Fund - Growth", "category": "Large Cap"},
    {"id": "MIRAE-LC-GROWTH", "name": "Mirae Asset Large Cap - Growth", "category": "Large Cap"},
    {"id": "NIPPON-SC-GROWTH", "name": "Nippon Small Cap Fund - Growth", "category": "Small Cap"},
]

BENCHMARK = {"id": "NIFTY50-TRI", "name": "Nifty 50 TRI"}

START_DATE = date(2017, 1, 1)
END_DATE = date(2024, 11, 30)
BASE_NAV = 100.0
BASE_BM = 1000.0


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5  # Mon=0 … Fri=4


def generate_nav_series(
    start_nav: float,
    annual_drift: float,
    annual_vol: float,
) -> list[tuple[date, float]]:
    """
    Simulate a daily NAV series using geometric Brownian motion.
    Returns list of (date, nav) for trading days only.
    """
    daily_drift = annual_drift / 252
    daily_vol = annual_vol / (252 ** 0.5)

    rows: list[tuple[date, float]] = []
    nav = start_nav
    current = START_DATE

    while current <= END_DATE:
        if is_trading_day(current):
            rows.append((current, round(nav, 4)))
            shock = random.gauss(daily_drift, daily_vol)
            nav *= 1 + shock
            nav = max(nav, 0.01)
        current += timedelta(days=1)

    return rows


def write_csv(path: str, rows: list[tuple[date, float]], header: list[str]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)
    print(f"  wrote {len(rows):,} rows → {path}")


def main(out_dir: str) -> None:
    random.seed(42)

    print("Generating synthetic NAV data …")

    # Benchmark
    bm_rows = generate_nav_series(BASE_BM, annual_drift=0.12, annual_vol=0.18)
    write_csv(
        os.path.join(out_dir, "benchmark_navs.csv"),
        [(d, nav) for d, nav in bm_rows],
        ["date", "nav"],
    )

    # Funds — each with slightly different drift/vol
    fund_params = [
        (0.14, 0.20),  # HDFC: slightly above market
        (0.13, 0.19),
        (0.12, 0.21),
        (0.11, 0.22),
        (0.16, 0.28),  # Small cap: higher vol
    ]

    fund_rows: list[tuple[str, str, str, float]] = []
    for fund, (drift, vol) in zip(FUNDS, fund_params):
        rows = generate_nav_series(BASE_NAV, annual_drift=drift, annual_vol=vol)
        for d, nav in rows:
            fund_rows.append((fund["id"], fund["category"], d.isoformat(), nav))

    fund_csv_path = os.path.join(out_dir, "fund_navs.csv")
    write_csv(
        fund_csv_path,
        [(fid, cat, dt, nav) for fid, cat, dt, nav in fund_rows],
        ["fund_id", "category", "date", "nav"],
    )

    # Fund metadata
    meta_path = os.path.join(out_dir, "fund_metadata.csv")
    with open(meta_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["fund_id", "name", "category", "benchmark_id"])
        for fund in FUNDS:
            writer.writerow([fund["id"], fund["name"], fund["category"], BENCHMARK["id"]])
    print(f"  wrote {len(FUNDS)} rows → {meta_path}")

    print("Done. Load these CSVs into staging tables once schema exists (milestone 2).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate synthetic NAV data for development")
    parser.add_argument(
        "--out-dir",
        default=os.path.join(os.path.dirname(__file__), "..", "data", "synthetic"),
        help="Output directory for CSV files",
    )
    args = parser.parse_args()
    main(args.out_dir)
