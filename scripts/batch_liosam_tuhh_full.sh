#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "$0")/.." && pwd)
CHAIN_LOCK="$PROJECT_ROOT/.chain.lock"
if ! mkdir "$CHAIN_LOCK" 2>/dev/null; then
    echo "another batch holds $CHAIN_LOCK" >&2
    exit 3
fi
trap 'rmdir "$CHAIN_LOCK" 2>/dev/null || true' EXIT INT TERM

ROOT=results/liosam_full/mcd_tuhh_day_04
for variant in FG-BA FG-B0 GE-BA GE-B0; do
    output="$PROJECT_ROOT/$ROOT/$variant"
    if [[ -f "$output/state_log.csv" && -f "$output/odometry.csv" ]] && \
       rg -q '^finished_at=' "$output/run_meta.txt"; then
        echo "skip completed $variant"
        continue
    fi
    "$PROJECT_ROOT/scripts/run_liosam_mcd_ablation.sh" \
        "$variant" handheld \
        data/mcd/tuhh_day_04/os1.bag data/mcd/tuhh_day_04/vn200.bag \
        "$ROOT/$variant" 0 187 0.25
done

"$PROJECT_ROOT/.venv/bin/python" \
    "$PROJECT_ROOT/scripts/validate_liosam_ablation.py" \
    "$PROJECT_ROOT/$ROOT"
