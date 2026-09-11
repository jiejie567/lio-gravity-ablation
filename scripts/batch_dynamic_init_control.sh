#!/usr/bin/env bash
# Quasi-static controls matched to the 60 s dynamic-start initialization pilot.
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
echo "quasi-static controls for dynamic-start pilot" > "$CHAIN_LOCK/what"
trap cleanup_lock EXIT INT TERM

run_one() {
    local bag=$1 seq=$2 config=$3 start=$4 rate=$5 run=$6 launch=$7
    if [ -f "results/$seq/$run/state_log.csv" ]; then
        echo "== skip: $seq/$run"
        return 0
    fi
    ./scripts/run_experiment.sh A "$bag" \
        -c "$config" -x configs/exp_tuning.yaml \
        -S "$start" -u 60 -q "$seq" -r "$rate" -p \
        -n "$run" -L "$launch"
}

run_one data/mcd/tuhh_day_04_os1 tuhh_day_04_quietinit_s6p679 \
    /work/configs/mcd_hhs_os1_imuint_off01.yaml 6.679 2.0 A mapping_exp
run_one data/mcd/tuhh_day_04_os1 tuhh_day_04_quietinit_s6p679 \
    /work/configs/mcd_hhs_os1_imuint_off01.yaml 6.679 2.0 RED21 mapping_exp_redg
.venv/bin/python scripts/validate_dynamic_init.py \
    tuhh_day_04_quietinit_s6p679 data/mcd/tuhh_day_04_os1/os1.bag \
    --start-sec 6.679 --duration-sec 60

run_one data/mcd/ntu_day_10_os1 ntu_day_10_quietinit_s14p683 \
    /work/configs/mcd_atv_os1_imuint_off01.yaml 14.683 1.5 A mapping_exp
run_one data/mcd/ntu_day_10_os1 ntu_day_10_quietinit_s14p683 \
    /work/configs/mcd_atv_os1_imuint_off01.yaml 14.683 1.5 RED21 mapping_exp_redg
.venv/bin/python scripts/validate_dynamic_init.py \
    ntu_day_10_quietinit_s14p683 data/mcd/ntu_day_10_os1/os1.bag \
    --start-sec 14.683 --duration-sec 60

echo "DYNAMIC_INIT_CONTROL_DONE $(date '+%Y-%m-%d %H:%M:%S')"
