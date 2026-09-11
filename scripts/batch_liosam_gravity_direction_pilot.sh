#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "$0")/.." && pwd)
CHAIN_LOCK="$PROJECT_ROOT/.chain.lock"
if ! mkdir "$CHAIN_LOCK" 2>/dev/null; then
    echo "another batch holds $CHAIN_LOCK" >&2
    exit 3
fi
trap 'rmdir "$CHAIN_LOCK" 2>/dev/null || true' EXIT INT TERM

ROOT=results/liosam_gravity_direction_pilot/m2dgr_hall05_60s
BAG=data/m2dgr/hall_05/lidar_imu.bag
DIRECTION_SIGMA=0.03490658503988659

for variant in FG-BA GE-BA; do
    for mode in D0 D1; do
        output="$PROJECT_ROOT/$ROOT/${variant}_${mode}"
        if [[ -f "$output/state_log.csv" && -f "$output/odometry.csv" ]] && \
           rg -q '^finished_at=' "$output/run_meta.txt"; then
            echo "skip completed ${variant}_${mode}"
            continue
        fi
        if [[ "$mode" = D1 ]]; then
            sigma=$DIRECTION_SIGMA
        else
            sigma=0
        fi
        "$PROJECT_ROOT/scripts/run_liosam_gravity_direction.sh" \
            "$variant" "$BAG" "$ROOT/${variant}_${mode}" \
            "$sigma" 0 60 0.5
    done
done

"$PROJECT_ROOT/.venv/bin/python" \
    "$PROJECT_ROOT/scripts/validate_liosam_gravity_direction.py" \
    "$PROJECT_ROOT/$ROOT"
