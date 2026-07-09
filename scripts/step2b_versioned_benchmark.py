"""
Step 2b: Convert selfmade_scheme_category_benchmark to an append-only
versioned schema, fixing the CLAUDE.md rule-5 violation in step2.

Creates:
  selfmade_benchmark_version  — version pointer table
  selfmade_scheme_category_benchmark_current  — view over active version

Migrates the existing data (currently no version column) by adding
a version_number column and backfilling existing rows as version 1.

After this script, step2_real_index_benchmarks.py should INSERT new
version rows instead of DROP+CREATE — a TODO left in that script.

Idempotent: safe to run multiple times.
"""

import os

import psycopg2

DB_HOST     = os.environ.get("DB_HOST", "localhost")
DB_PORT     = os.environ.get("DB_PORT", "5432")
DB_NAME     = os.environ.get("DB_NAME", "Altstreet_AI")
DB_USER     = os.environ.get("DB_USER", "piyushrajlenka")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")


def main() -> None:
    conn = psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASSWORD,
    )
    conn.autocommit = False
    cur = conn.cursor()

    print("Step 2b: Converting selfmade_scheme_category_benchmark to versioned ...")

    # ── Create version pointer table ─────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS selfmade_benchmark_version (
            id             SERIAL PRIMARY KEY,
            version_number INT  NOT NULL UNIQUE,
            description    TEXT,
            is_active      BOOLEAN NOT NULL DEFAULT FALSE,
            created_at     TIMESTAMP DEFAULT NOW()
        );
    """)

    # ── Add version_number column to mapping table if absent ─────────────
    cur.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'selfmade_scheme_category_benchmark'
          AND column_name = 'version_number';
    """)
    if not cur.fetchone():
        print("  Adding version_number column to selfmade_scheme_category_benchmark ...")
        cur.execute("""
            ALTER TABLE selfmade_scheme_category_benchmark
            ADD COLUMN version_number INT NOT NULL DEFAULT 1;
        """)
        # Remove the DEFAULT so future inserts must be explicit
        cur.execute("""
            ALTER TABLE selfmade_scheme_category_benchmark
            ALTER COLUMN version_number DROP DEFAULT;
        """)
        print("  Column added.")

    # ── Ensure version 1 row exists and is active ─────────────────────────
    cur.execute("SELECT COUNT(*) FROM selfmade_benchmark_version WHERE version_number = 1;")
    if cur.fetchone()[0] == 0:
        cur.execute("""
            INSERT INTO selfmade_benchmark_version (version_number, description, is_active)
            VALUES (1, 'Initial backfill — step2_real_index_benchmarks.py run', TRUE);
        """)
        print("  Inserted version 1 into selfmade_benchmark_version.")
    else:
        cur.execute(
            "UPDATE selfmade_benchmark_version SET is_active = FALSE WHERE version_number != 1;"
        )
        cur.execute(
            "UPDATE selfmade_benchmark_version SET is_active = TRUE WHERE version_number = 1;"
        )
        print("  Version 1 already exists — marked active.")

    # ── Create the current view ───────────────────────────────────────────
    cur.execute("""
        CREATE OR REPLACE VIEW selfmade_scheme_category_benchmark_current AS
            SELECT b.*
            FROM selfmade_scheme_category_benchmark b
            JOIN selfmade_benchmark_version v ON v.version_number = b.version_number
            WHERE v.is_active = TRUE;
    """)
    print("  View selfmade_scheme_category_benchmark_current created/updated.")

    conn.commit()

    # ── Verification ──────────────────────────────────────────────────────
    cur.execute("""
        SELECT version_number, description, is_active, created_at
        FROM selfmade_benchmark_version ORDER BY version_number;
    """)
    print("\n  selfmade_benchmark_version:")
    for row in cur.fetchall():
        print(f"    v{row[0]}  active={row[2]}  {row[1]}  {row[3].date() if row[3] else ''}")

    cur.execute("SELECT COUNT(*) FROM selfmade_scheme_category_benchmark_current;")
    print(f"\n  Rows in current view: {cur.fetchone()[0]}")

    cur.close()
    conn.close()
    print("\nStep 2b complete.  Future runs of step2_real_index_benchmarks.py")
    print("should INSERT a new version instead of DROP+CREATE the whole table.")


if __name__ == "__main__":
    main()
