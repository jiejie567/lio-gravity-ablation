#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "$0")/.." && pwd)
CHAIN_LOCK="$PROJECT_ROOT/.chain.lock"
if ! mkdir "$CHAIN_LOCK" 2>/dev/null; then
    echo "another batch holds $CHAIN_LOCK" >&2
    exit 3
fi
trap 'rmdir "$CHAIN_LOCK" 2>/dev/null || true' EXIT INT TERM

BAG=data/m2dgr/hall_05/lidar_imu.bag
ROOT=results/liosam_pilot/hall05_60s

for variant in FG-BA FG-B0 GE-BA GE-B0; do
    output="$PROJECT_ROOT/$ROOT/$variant"
    if [[ -f "$output/state_log.csv" && -f "$output/odometry.csv" ]]; then
        echo "skip completed $variant"
        continue
    fi
    "$PROJECT_ROOT/scripts/run_liosam_ablation.sh" \
        "$variant" "$BAG" "$ROOT/$variant" 0 60 0.5
done
