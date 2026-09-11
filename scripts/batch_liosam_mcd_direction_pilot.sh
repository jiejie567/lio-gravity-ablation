#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "$0")/.." && pwd)
CHAIN_LOCK="$PROJECT_ROOT/.chain.lock"
if ! mkdir "$CHAIN_LOCK" 2>/dev/null; then
    echo "another batch holds $CHAIN_LOCK" >&2
    exit 3
fi
trap 'rmdir "$CHAIN_LOCK" 2>/dev/null || true' EXIT INT TERM

ROOT=results/liosam_gravity_direction_pilot/mcd_tuhh_day04_30s
LIDAR=data/mcd/tuhh_day_04/os1.bag
IMU=data/mcd/tuhh_day_04/vn200.bag

for variant in FG-BA GE-BA; do
    for level in off s2; do
        if [[ "$level" = off ]]; then
            sigma=0
        else
            sigma=0.03490658503988659
        fi
        output="$PROJECT_ROOT/$ROOT/${variant}_${level}"
        if [[ -f "$output/state_log.csv" && -f "$output/odometry.csv" ]] && \
           rg -q '^finished_at=' "$output/run_meta.txt"; then
            echo "skip completed ${variant}_${level}"
            continue
        fi
        "$PROJECT_ROOT/scripts/run_liosam_mcd_gravity_direction.sh" \
            "$variant" handheld "$LIDAR" "$IMU" \
            "$ROOT/${variant}_${level}" "$sigma" 0 30 0.25
    done
done

"$PROJECT_ROOT/.venv/bin/python" \
    "$PROJECT_ROOT/scripts/validate_liosam_direction_sweep.py" \
    "$PROJECT_ROOT/$ROOT" --levels off,s2
