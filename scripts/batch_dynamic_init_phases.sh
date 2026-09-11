#!/usr/bin/env bash
# Additional low-gyro dynamic-start phases for trajectory-level robustness.
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
    rm -f "$CHAIN_LOCK/pid" "$CHAIN_LOCK/what"
    rmdir "$CHAIN_LOCK"
    mkdir "$CHAIN_LOCK"
fi
echo $$ > "$CHAIN_LOCK/pid"
echo "additional dynamic-start phases" > "$CHAIN_LOCK/what"
trap cleanup_lock EXIT INT TERM

run_pair() {
    local bag=$1 seq=$2 config=$3 start=$4 rate=$5 bag_file=$6
    if [ ! -f "results/$seq/A/state_log.csv" ]; then
        ./scripts/run_experiment.sh A "$bag" -c "$config" \
            -x configs/exp_tuning.yaml -S "$start" -u 60 -q "$seq" \
            -r "$rate" -p -n A -L mapping_exp
    fi
    if [ ! -f "results/$seq/RED21/state_log.csv" ]; then
        ./scripts/run_experiment.sh A "$bag" -c "$config" \
            -x configs/exp_tuning.yaml -S "$start" -u 60 -q "$seq" \
            -r "$rate" -p -n RED21 -L mapping_exp_redg
    fi
    .venv/bin/python scripts/validate_dynamic_init.py "$seq" "$bag_file" \
        --start-sec "$start" --duration-sec 60
}

run_pair data/mcd/tuhh_day_04_os1 tuhh_day_04_dyninit_s38p271 \
    /work/configs/mcd_hhs_os1_imuint_off01.yaml 38.271 2.0 \
    data/mcd/tuhh_day_04_os1/os1.bag
run_pair data/mcd/tuhh_day_04_os1 tuhh_day_04_dyninit_s98p779 \
    /work/configs/mcd_hhs_os1_imuint_off01.yaml 98.779 2.0 \
    data/mcd/tuhh_day_04_os1/os1.bag

run_pair data/mcd/ntu_day_10_os1 ntu_day_10_dyninit_s66p476 \
    /work/configs/mcd_atv_os1_imuint_off01.yaml 66.476 1.5 \
    data/mcd/ntu_day_10_os1/os1.bag
run_pair data/mcd/ntu_day_10_os1 ntu_day_10_dyninit_s78p568 \
    /work/configs/mcd_atv_os1_imuint_off01.yaml 78.568 1.5 \
    data/mcd/ntu_day_10_os1/os1.bag

echo "DYNAMIC_INIT_PHASES_DONE $(date '+%Y-%m-%d %H:%M:%S')"
