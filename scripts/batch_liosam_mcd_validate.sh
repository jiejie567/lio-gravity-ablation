#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "$0")/.." && pwd)
CHAIN_LOCK="$PROJECT_ROOT/.chain.lock"
if ! mkdir "$CHAIN_LOCK" 2>/dev/null; then
    echo "another batch holds $CHAIN_LOCK" >&2
    exit 3
fi
trap 'rmdir "$CHAIN_LOCK" 2>/dev/null || true' EXIT INT TERM

ROOT=results/liosam_validation/mcd_ntu_day_10_30s_queued
for variant in FG-BA FG-B0 GE-BA GE-B0; do
    output="$PROJECT_ROOT/$ROOT/$variant"
    if [[ -f "$output/state_log.csv" && -f "$output/odometry.csv" ]]; then
        echo "skip completed $variant"
        continue
    fi
    "$PROJECT_ROOT/scripts/run_liosam_mcd_ablation.sh" \
        "$variant" atv \
        data/mcd/ntu_day_10/os1.bag \
        data/mcd/ntu_day_10/vn100.bag \
        "$ROOT/$variant" 0 30 0.5
done
