#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "$0")/.." && pwd)
CHAIN_LOCK="$PROJECT_ROOT/.chain.lock"
if ! mkdir "$CHAIN_LOCK" 2>/dev/null; then
    echo "another batch holds $CHAIN_LOCK" >&2
    exit 3
fi
trap 'rmdir "$CHAIN_LOCK" 2>/dev/null || true' EXIT INT TERM

levels=(s2 off s0p5 s5)
sigmas=(0.03490658503988659 0 0.008726646259971648 0.08726646259971647)

M2_ROOT=results/liosam_direction_full/m2dgr_hall05
for index in 0 1 2 3; do
    for variant in FG-BA GE-BA; do
        level=${levels[$index]}
        sigma=${sigmas[$index]}
        output="$PROJECT_ROOT/$M2_ROOT/${variant}_${level}"
        if [[ -f "$output/state_log.csv" && -f "$output/odometry.csv" ]] && \
           rg -q '^finished_at=' "$output/run_meta.txt"; then
            echo "skip completed m2dgr ${variant}_${level}"
            continue
        fi
        "$PROJECT_ROOT/scripts/run_liosam_gravity_direction.sh" \
            "$variant" data/m2dgr/hall_05/lidar_imu.bag \
            "$M2_ROOT/${variant}_${level}" "$sigma" 0 400 0.5
    done
done
"$PROJECT_ROOT/.venv/bin/python" \
    "$PROJECT_ROOT/scripts/validate_liosam_direction_sweep.py" \
    "$PROJECT_ROOT/$M2_ROOT"

MCD_ROOT=results/liosam_direction_full/mcd_tuhh_day04
for index in 0 1 2 3; do
    for variant in FG-BA GE-BA; do
        level=${levels[$index]}
        sigma=${sigmas[$index]}
        output="$PROJECT_ROOT/$MCD_ROOT/${variant}_${level}"
        if [[ -f "$output/state_log.csv" && -f "$output/odometry.csv" ]] && \
           rg -q '^finished_at=' "$output/run_meta.txt"; then
            echo "skip completed mcd ${variant}_${level}"
            continue
        fi
        "$PROJECT_ROOT/scripts/run_liosam_mcd_gravity_direction.sh" \
            "$variant" handheld data/mcd/tuhh_day_04/os1.bag \
            data/mcd/tuhh_day_04/vn200.bag \
            "$MCD_ROOT/${variant}_${level}" "$sigma" 0 187 0.25
    done
done
"$PROJECT_ROOT/.venv/bin/python" \
    "$PROJECT_ROOT/scripts/validate_liosam_direction_sweep.py" \
    "$PROJECT_ROOT/$MCD_ROOT"
