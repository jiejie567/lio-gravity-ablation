#!/usr/bin/env bash
# Serial paired runtime benchmark: 23D Online versus true-manifold 21D FixG.
# Usage: ./scripts/batch_runtime_true_dim.sh [number_of_pairs, default 3]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PAIRS=${1:-3}
case "$PAIRS" in 1|2|3) ;; *) echo "number_of_pairs must be 1, 2, or 3" >&2; exit 2;; esac

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
    rm -f "$CHAIN_LOCK/pid" "$CHAIN_LOCK/what"
    rmdir "$CHAIN_LOCK"
    mkdir "$CHAIN_LOCK"
fi
echo $$ > "$CHAIN_LOCK/pid"
echo "true-manifold Online/FixG paired runtime benchmark" > "$CHAIN_LOCK/what"
trap cleanup_lock EXIT INT TERM

BAG="data/mcd/ntu_day_10/os1.bag"
BASE_CONFIG="/work/configs/mcd_atv_os1_imuint_off01.yaml"
OVERLAY="configs/runtime_benchmark.yaml"
RESULT_ROOT="$ROOT/results/os1/runtime_true_dim_ntu_day_10"
SHARED_LOG="$ROOT/catkin_ws/src/FAST_LIO/Log/fast_lio_time_log.csv"
mkdir -p "$RESULT_ROOT"

archive_unattributed_log() {
    if [ -f "$SHARED_LOG" ]; then
        stamp=$(date '+%Y%m%dT%H%M%S')
        target="$RESULT_ROOT/unattributed_time_log_${stamp}.csv"
        echo "Archiving pre-existing shared timing log to $target"
        mv "$SHARED_LOG" "$target"
    fi
}

run_one() {
    local method=$1 repeat=$2 launch=$3
    local run_name="runtime_true_dim_ntu_day_10/${method}_r${repeat}"
    local run_dir="$ROOT/results/os1/$run_name"

    if [ -f "$run_dir/state_log.csv" ] && [ -f "$run_dir/runtime_log.csv" ]; then
        echo "== skip complete: $method r$repeat"
        return 0
    fi
    if [ -e "$run_dir/state_log.csv" ] || [ -e "$run_dir/runtime_log.csv" ]; then
        echo "Incomplete benchmark directory exists; inspect before rerunning: $run_dir" >&2
        exit 4
    fi
    [ ! -e "$SHARED_LOG" ] || { echo "Shared timing log was not archived" >&2; exit 5; }

    echo "== start: $method r$repeat $(date '+%Y-%m-%d %H:%M:%S')"
    ./scripts/run_experiment.sh A "$BAG" \
        -c "$BASE_CONFIG" -x "$OVERLAY" -n "$run_name" \
        -L "$launch" -r 1 -p

    [ -s "$SHARED_LOG" ] || { echo "Timing log missing after $method r$repeat" >&2; exit 6; }
    mv "$SHARED_LOG" "$run_dir/runtime_log.csv"
    rg -q '^fastlio_binary_sha1: [0-9a-f]{12}$' "$run_dir/run_meta.txt" || {
        echo "Binary fingerprint missing for $method r$repeat" >&2; exit 7;
    }
    echo "== finish: $method r$repeat $(date '+%Y-%m-%d %H:%M:%S')"
}

archive_unattributed_log
for repeat in $(seq 1 "$PAIRS"); do
    # Reverse the second pair to reduce monotonic thermal/order confounding.
    if [ "$repeat" -eq 2 ]; then
        run_one RED21 "$repeat" mapping_exp_redg
        sleep 10
        run_one A "$repeat" mapping_exp
    else
        run_one A "$repeat" mapping_exp
        sleep 10
        run_one RED21 "$repeat" mapping_exp_redg
    fi
    .venv/bin/python scripts/collect_runtime_benchmark.py --allow-incomplete
    [ "$repeat" -eq "$PAIRS" ] || sleep 10
done

echo "RUNTIME_TRUE_DIM_DONE $(date '+%Y-%m-%d %H:%M:%S')"
