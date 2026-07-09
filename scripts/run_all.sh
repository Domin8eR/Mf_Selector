#!/usr/bin/env bash
# Run all data foundation scripts in order.
# Usage: ./scripts/run_all.sh

set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== MFit Data Foundation Pipeline ==="
echo ""

python3 "$DIR/step1_category_benchmark.py"
python3 "$DIR/step2_scheme_returns.py"
python3 "$DIR/step3_scheme_metrics.py"
python3 "$DIR/step4_scheme_ranking.py"

echo "=== All steps complete ==="
