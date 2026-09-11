#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "$0")/.." && pwd)
CHAIN_LOCK="$PROJECT_ROOT/.chain.lock"
if ! mkdir "$CHAIN_LOCK" 2>/dev/null; then
    echo "another batch holds $CHAIN_LOCK" >&2
    exit 3
fi
trap 'rmdir "$CHAIN_LOCK" 2>/dev/null || true' EXIT INT TERM

ROOT=results/liosam_direction_dropout/mcd_tuhh_day04_drop5x20
LIDAR=data/mcd/degraded/tuhh_day_04_drop5x20.bag
IMU=data/mcd/tuhh_day_04/vn200.bag
for level in off s2; do
    for variant in FG-BA GE-BA; do
        if [[ "$level" = off ]]; then
            sigma=0
        else
            sigma=0.03490658503988659
        fi
        output="$PROJECT_ROOT/$ROOT/${variant}_${level}"
        if [[ -f "$output/state_log.csv" && -f "$output/odometry.csv" ]] && \
           rg -q '^finished_at=' "$output/run_meta.txt"; then
            echo "skip completed drop5x20 ${variant}_${level}"
            continue
        fi
        "$PROJECT_ROOT/scripts/run_liosam_mcd_gravity_direction.sh" \
            "$variant" handheld "$LIDAR" "$IMU" \
            "$ROOT/${variant}_${level}" "$sigma" 0 187 0.25
    done
done
"$PROJECT_ROOT/.venv/bin/python" \
    "$PROJECT_ROOT/scripts/validate_liosam_direction_sweep.py" \
    "$PROJECT_ROOT/$ROOT" --levels off,s2
