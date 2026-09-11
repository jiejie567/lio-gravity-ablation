#!/usr/bin/env bash
# True-dimension IMU-weight stress test.
#
# Compare the original 23D manifold (A) against the 21D manifold with gravity
# removed (RED21) while scaling all IMU process-noise terms.  Each pair uses
# the same sequence, sensor configuration, tuning overlay, and playback rate.
# Runs are strictly serial and the batch is re-entrant.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

CHAIN_LOCK="$ROOT/.chain.lock"
cleanup_lock() {
    if [ -f "$CHAIN_LOCK/pid" ] && [ "$(sed -n '1p' "$CHAIN_LOCK/pid")" = "$$" ]; then
        rm -f "$CHAIN_LOCK/pid" "$CHAIN_LOCK/what"
        rmdir "$CHAIN_LOCK" 2>/dev/null || true
    fi
}

if ! mkdir "$CHAIN_LOCK" 2>/dev/null; then
    owner="$(sed -n '1p' "$CHAIN_LOCK/pid" 2>/dev/null || true)"
    if [ -n "$owner" ] && kill -0 "$owner" 2>/dev/null; then
        echo "Refusing to start: another experiment queue is active (pid $owner)." >&2
        exit 3
    fi
    echo "Removing stale queue lock (pid ${owner:-unknown})." >&2
    rm -f "$CHAIN_LOCK/pid" "$CHAIN_LOCK/what"
    rmdir "$CHAIN_LOCK"
    mkdir "$CHAIN_LOCK"
fi
echo $$ > "$CHAIN_LOCK/pid"
echo "true-dimension Online/RED21 IMU-weight sweep" > "$CHAIN_LOCK/what"
trap cleanup_lock EXIT INT TERM

ATV=/work/configs/mcd_atv_os1_imuint_off01.yaml

run_one() {
    local seq=$1
    local run_name=$2
    local launch=$3
    local overlay=$4
    local rate=$5
    local log="results/$seq/$run_name/state_log.csv"

    if [ -f "$log" ]; then
        echo "== skip: $seq/$run_name"
        return 0
    fi

    echo "== start: $seq/$run_name  $(date '+%Y-%m-%d %H:%M:%S')"
    ./scripts/run_experiment.sh A "data/mcd/$seq" \
        -c "$ATV" -x "$overlay" -n "$run_name" -L "$launch" -r "$rate" -p
    echo "== done:  $seq/$run_name  $(date '+%Y-%m-%d %H:%M:%S')"
}

run_pair() {
    local seq=$1
    local label=$2
    local overlay=$3
    local rate=$4
    local suffix="_tdim_imuw${label}"

    run_one "$seq" "A${suffix}" mapping_exp "$overlay" "$rate"
    run_one "$seq" "RED21${suffix}" mapping_exp_redg "$overlay" "$rate"
}

# Pair adjacent runs to minimize environmental drift.  Smaller noise means
# greater confidence in inertial propagation.
for seq in ntu_day_10_os1 ntu_night_04_os1; do
    run_pair "$seq" 1     configs/exp_tuning.yaml          1.5
    run_pair "$seq" 0p1   configs/exp_tuning_imuw0p1.yaml  1.5
    run_pair "$seq" 0p01  configs/exp_tuning_imuw0p01.yaml 1.5
    run_pair "$seq" 10    configs/exp_tuning_imuw10.yaml   1.5
done

echo "RED21_IMUW_BATCH_DONE $(date '+%Y-%m-%d %H:%M:%S')"
