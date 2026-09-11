#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "$0")/.." && pwd)
CHAIN_LOCK="$PROJECT_ROOT/.chain.lock"
if ! mkdir "$CHAIN_LOCK" 2>/dev/null; then
    echo "another batch holds $CHAIN_LOCK" >&2
    exit 3
fi
trap 'rmdir "$CHAIN_LOCK" 2>/dev/null || true' EXIT INT TERM

run_mcd_sequence()
{
    local sequence=$1
    local setup=$2
    local lidar_bag=$3
    local imu_bag=$4
    local duration=$5
    local root="results/liosam_full/$sequence"
    for variant in FG-BA FG-B0 GE-BA GE-B0; do
        local output="$PROJECT_ROOT/$root/$variant"
        if [[ -f "$output/state_log.csv" && -f "$output/odometry.csv" ]]; then
            echo "skip completed $sequence/$variant"
            continue
        fi
        "$PROJECT_ROOT/scripts/run_liosam_mcd_ablation.sh" \
            "$variant" "$setup" "$lidar_bag" "$imu_bag" \
            "$root/$variant" 0 "$duration" 0.25
    done
    "$PROJECT_ROOT/.venv/bin/python" \
        "$PROJECT_ROOT/scripts/validate_liosam_ablation.py" \
        "$PROJECT_ROOT/$root"
}

run_m2dgr_sequence()
{
    local root="results/liosam_full/m2dgr_hall05"
    for variant in FG-BA FG-B0 GE-BA GE-B0; do
        local output="$PROJECT_ROOT/$root/$variant"
        if [[ -f "$output/state_log.csv" && -f "$output/odometry.csv" ]]; then
            echo "skip completed m2dgr_hall05/$variant"
            continue
        fi
        "$PROJECT_ROOT/scripts/run_liosam_ablation.sh" \
            "$variant" data/m2dgr/hall_05/lidar_imu.bag \
            "$root/$variant" 0 400 0.25
    done
    "$PROJECT_ROOT/.venv/bin/python" \
        "$PROJECT_ROOT/scripts/validate_liosam_ablation.py" \
        "$PROJECT_ROOT/$root"
}

# Shorter setup first: a configuration error is caught before the expensive
# ATV and Hall runs.  The queue remains strictly serial throughout.
run_mcd_sequence mcd_tuhh_day_04 handheld \
    data/mcd/tuhh_day_04/os1.bag data/mcd/tuhh_day_04/vn200.bag 187
run_mcd_sequence mcd_ntu_day_10 atv \
    data/mcd/ntu_day_10/os1.bag data/mcd/ntu_day_10/vn100.bag 324
run_m2dgr_sequence
