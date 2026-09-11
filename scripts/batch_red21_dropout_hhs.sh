#!/usr/bin/env bash
# Cross-trajectory dropout check on the handheld tuhh-day-04 sequence.
# Degraded bags must already exist. Runs are strictly serial and re-entrant.
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
echo "true-manifold Online/FixG handheld dropout check" > "$CHAIN_LOCK/what"
trap cleanup_lock EXIT INT TERM

run_one() {
    local seq=$1 run_name=$2 launch=$3
    if [ -f "results/$seq/$run_name/state_log.csv" ]; then
        echo "== skip: $seq/$run_name"
        return 0
    fi
    ./scripts/run_experiment.sh A "data/mcd/$seq" \
        -c /work/configs/mcd_hhs_os1_imuint_off01.yaml \
        -x configs/exp_tuning.yaml -n "$run_name" -L "$launch" -r 1.5 -p
}

for seconds in 2 3 5; do
    seq="tuhh_day_04_drop${seconds}x20"
    run_one "$seq" A mapping_exp
    run_one "$seq" RED21 mapping_exp_redg
done

echo "RED21_DROPOUT_HHS_BATCH_DONE $(date '+%Y-%m-%d %H:%M:%S')"
