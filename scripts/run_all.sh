#!/usr/bin/env bash
# Run all data foundation scripts in order.
# Usage: ./scripts/run_all.sh

set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== AltStreet Data Foundation Pipeline ==="
echo ""

python3 "$DIR/step1_category_benchmark.py"
python3 "$DIR/step2_scheme_returns.py"
python3 "$DIR/step3_scheme_metrics.py"

# step4_scheme_ranking.py is retired (see its docstring) — its hardcoded
# formula never read selfmade_rule_component, so approving a rule version
# had no effect on what it computed. seed_category_rankings.py is now the
# one entry point: it bootstraps the rule engine tables (first run only)
# then calls the same governed recompute_all_rankings() that POST /rules/
# approve calls — one formula, whether triggered by approval or by this
# script. Run from backend/ so app.core.config finds backend/.env.
(cd "$DIR/../backend" && python3 "$DIR/seed_category_rankings.py")

echo "=== All steps complete ==="
