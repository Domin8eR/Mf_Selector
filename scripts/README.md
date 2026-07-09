# Scripts

Utility scripts for local development. Not part of the production app.

## seed_synthetic.py

Generates plausible NAV series for 5 synthetic funds + 1 benchmark using
geometric Brownian motion. Output: CSV files under `data/synthetic/`.

```bash
cd Mf_Selector
python scripts/seed_synthetic.py
# or specify output directory:
python scripts/seed_synthetic.py --out-dir ./data/synthetic
```

Files produced:
- `fund_navs.csv` — daily NAVs for 5 synthetic funds (trading days only)
- `benchmark_navs.csv` — Nifty 50 TRI proxy
- `fund_metadata.csv` — fund IDs, names, categories, benchmark mapping

These CSVs are loaded into staging tables in milestone 2 once the schema
and ingestion pipeline exist.

Rules honoured (same as production):
- Trading days only (Mon–Fri) — no weekend rows
- No forward-filled NAVs — every row is a simulated value
- Data starts 2017-01-01 to match the process note requirement
