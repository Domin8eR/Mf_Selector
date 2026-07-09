"""
Seed script for Home page backend data.

Creates:
  - selfmade_ranking_snapshot table (two point-in-time captures)
  - selfmade_workspace table (3 saved workspaces)

Then updates selfmade_scheme_ranking.rank_delta / rank_in_category_prev
from the snapshot diff so the insight engine sees real movement data.

Run from backend/ directory:
  python ../scripts/seed_home_data.py
"""

import os
import sys
import random
from datetime import date, timedelta

import psycopg2
from psycopg2.extras import execute_values

DB_DSN = os.getenv(
    "DATABASE_URL",
    "postgresql://piyushrajlenka:29062002@localhost:5432/Altstreet_AI",
)


def get_conn():
    return psycopg2.connect(DB_DSN)


# ── DDL ───────────────────────────────────────────────────────────────────────

CREATE_SNAPSHOT_TABLE = """
CREATE TABLE IF NOT EXISTS selfmade_ranking_snapshot (
    id              BIGSERIAL PRIMARY KEY,
    snapshot_date   DATE NOT NULL,
    category        VARCHAR(200) NOT NULL,
    schemecode      INTEGER NOT NULL,
    fund_name       VARCHAR(500),
    rank_in_category INTEGER NOT NULL,
    composite_score NUMERIC(10, 4),
    sharpe_score    NUMERIC(10, 4),
    sort_basis      VARCHAR(50) DEFAULT 'SHARPE_DESC',
    created_at      TIMESTAMP DEFAULT NOW(),
    UNIQUE(snapshot_date, category, schemecode)
);
"""

CREATE_WORKSPACE_TABLE = """
CREATE TABLE IF NOT EXISTS selfmade_workspace (
    id          BIGSERIAL PRIMARY KEY,
    name        VARCHAR(300) NOT NULL,
    description TEXT,
    owner       VARCHAR(200) DEFAULT 'rahul@altstreet.net',
    updated_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);
"""


def create_tables(cur):
    cur.execute(CREATE_SNAPSHOT_TABLE)
    cur.execute(CREATE_WORKSPACE_TABLE)
    print("Tables created (if not existed).")


# ── Snapshot seeding ──────────────────────────────────────────────────────────

TARGET_CATEGORIES = [
    "Equity — Large Cap",
    "Equity — Mid Cap",
    "Equity — Small Cap",
]

IMPROVER_PUSH = 8    # prev_rank = current_rank + IMPROVER_PUSH for seeded improvers
IMPROVER_COUNT = 5   # number of improvers to create per category


def seed_snapshots(cur, today: date):
    """Seed two ranking snapshots per category (prev = 7 days ago, current = today)."""
    prev_date = today - timedelta(days=7)

    for category in TARGET_CATEGORIES:
        # Fetch current rankings
        cur.execute(
            """
            SELECT schemecode, amfi_name, rank_in_category, composite_score, sharpe_ratio_3yr
            FROM selfmade_scheme_ranking
            WHERE category = %s
            ORDER BY rank_in_category
            """,
            (category,),
        )
        rows = cur.fetchall()
        if not rows:
            print(f"  No rows for {category} — skipping.")
            continue

        total = len(rows)
        print(f"  {category}: {total} funds")

        # ── Current snapshot (today) ────────────────────────────────────────
        current_data = [
            (today, category, r[0], r[1], r[2], r[3], r[4], "SHARPE_DESC")
            for r in rows
        ]
        execute_values(
            cur,
            """
            INSERT INTO selfmade_ranking_snapshot
                (snapshot_date, category, schemecode, fund_name,
                 rank_in_category, composite_score, sharpe_score, sort_basis)
            VALUES %s
            ON CONFLICT (snapshot_date, category, schemecode) DO NOTHING
            """,
            current_data,
        )

        # ── Previous snapshot (prev_date): perturb ranks ────────────────────
        # Pick IMPROVER_COUNT funds currently in top 30 to be "improvers"
        top30 = [r for r in rows if r[2] <= 30]
        random.seed(42)  # deterministic
        improver_schemecodes = set(
            r[0] for r in random.sample(top30, min(IMPROVER_COUNT, len(top30)))
        )

        prev_data = []
        for r in rows:
            sc, name, curr_rank, score, sharpe = r
            if sc in improver_schemecodes:
                # Was ranked lower (worse) in the previous snapshot
                prev_rank = curr_rank + IMPROVER_PUSH
            else:
                # Slight random noise ±2 for non-improvers, clamped to 1..total
                noise = random.randint(-2, 2)
                prev_rank = max(1, min(total, curr_rank + noise))

            prev_data.append(
                (prev_date, category, sc, name, prev_rank, score, sharpe, "SHARPE_DESC")
            )

        execute_values(
            cur,
            """
            INSERT INTO selfmade_ranking_snapshot
                (snapshot_date, category, schemecode, fund_name,
                 rank_in_category, composite_score, sharpe_score, sort_basis)
            VALUES %s
            ON CONFLICT (snapshot_date, category, schemecode) DO NOTHING
            """,
            prev_data,
        )

        # ── Update selfmade_scheme_ranking with diff ────────────────────────
        prev_rank_by_sc = {r[2]: r[4] for r in prev_data}  # prev_data index 2=sc, 4=prev_rank
        # Rebuild: need schemecode → prev_rank mapping
        prev_rank_map = {}
        for rec in prev_data:
            prev_date_val, _cat, sc, _name, prev_rank, _score, _sharpe, _sb = rec
            prev_rank_map[sc] = prev_rank

        for r in rows:
            sc, _name, curr_rank, _score, _sharpe = r
            prev_rank = prev_rank_map.get(sc)
            if prev_rank is not None:
                rank_delta = curr_rank - prev_rank
                cur.execute(
                    """
                    UPDATE selfmade_scheme_ranking
                    SET rank_in_category_prev = %s,
                        rank_delta = %s
                    WHERE schemecode = %s AND category = %s
                    """,
                    (prev_rank, rank_delta, sc, category),
                )

    print("  Snapshot seeding complete.")


# ── Workspace seeding ─────────────────────────────────────────────────────────

WORKSPACES = [
    {
        "name": "Large Cap IR Slope Analysis",
        "description": "Structural improvement signals in large cap category — 3Y IR slope filter",
        "updated_at": date.today() - timedelta(days=1),
    },
    {
        "name": "Flexi Cap Comparison — SBI vs HDFC",
        "description": "Side-by-side comparison of SBI Flexi Cap and HDFC Flexi Cap on Sharpe and consistency",
        "updated_at": date.today() - timedelta(days=4),
    },
    {
        "name": "Small Cap DQ Check",
        "description": "Data quality review for small cap universe — NAV coverage and ratio completeness",
        "updated_at": date.today() - timedelta(days=9),
    },
]


def seed_workspaces(cur):
    cur.execute("SELECT COUNT(*) FROM selfmade_workspace")
    existing = cur.fetchone()[0]
    if existing >= 3:
        print(f"  selfmade_workspace already has {existing} rows — skipping.")
        return

    for ws in WORKSPACES:
        cur.execute(
            """
            INSERT INTO selfmade_workspace (name, description, updated_at)
            VALUES (%s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (ws["name"], ws["description"], ws["updated_at"]),
        )
    print(f"  Seeded {len(WORKSPACES)} workspaces.")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    today = date.today()
    print(f"Seed date: {today}")

    conn = get_conn()
    conn.autocommit = False
    cur = conn.cursor()

    try:
        print("\n[1] Creating tables…")
        create_tables(cur)

        print("\n[2] Seeding ranking snapshots…")
        seed_snapshots(cur, today)

        print("\n[3] Seeding workspaces…")
        seed_workspaces(cur)

        conn.commit()
        print("\nDone. All data committed.")

    except Exception as e:
        conn.rollback()
        print(f"\nERROR: {e}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
