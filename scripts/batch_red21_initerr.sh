#!/usr/bin/env bash
# True-manifold initialization-error stress test: Online (23D) vs FixG (21D).
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
    rm -f "$CHAIN_LOCK/pid" "$CHAIN_LOCK/what"
    rmdir "$CHAIN_LOCK"
    mkdir "$CHAIN_LOCK"
fi
echo $$ > "$CHAIN_LOCK/pid"
echo "true-manifold Online/FixG initialization-error sweep" > "$CHAIN_LOCK/what"
trap cleanup_lock EXIT INT TERM

run_one() {
    local seq=$1 config=$2 err=$3 run_name=$4 launch=$5
    if [ -f "results/$seq/$run_name/state_log.csv" ]; then
        echo "== skip: $seq/$run_name"
        return 0
    fi
    ./scripts/run_experiment.sh A "data/mcd/$seq" \
        -c "$config" -x configs/exp_tuning.yaml -e "$err" \
        -n "$run_name" -L "$launch" -r 1.5 -p
}

run_pair() {
    local seq=$1 config=$2 err=$3 label=$4
    run_one "$seq" "$config" "$err" "A_tdim_err${label}" mapping_exp
    run_one "$seq" "$config" "$err" "RED21_tdim_err${label}" mapping_exp_redg
}

for err_spec in "0.5:0p5" "1:1" "2:2"; do
    err=${err_spec%%:*}
    label=${err_spec##*:}
    run_pair tuhh_day_04_os1 /work/configs/mcd_hhs_os1_imuint_off01.yaml "$err" "$label"
    run_pair ntu_day_10_os1 /work/configs/mcd_atv_os1_imuint_off01.yaml "$err" "$label"
done

echo "RED21_INITERR_BATCH_DONE $(date '+%Y-%m-%d %H:%M:%S')"
