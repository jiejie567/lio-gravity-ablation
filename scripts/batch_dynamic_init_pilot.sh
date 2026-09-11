#!/usr/bin/env bash
# Dynamic-start initialization pilot: true 23D Online vs true 21D FixG.
# Each pair replays the same 60 s suffix from a translation-dominant start.
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
echo "dynamic-start Online/FixG pilot" > "$CHAIN_LOCK/what"
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

# The offsets are 20 ms before the selected LiDAR scan.  In the following
# initialization window the mean gyro is <0.05 rad/s, limiting gyro-bias
# confounding while the mean acceleration is inconsistent with static gravity.
run_one data/mcd/tuhh_day_04_os1  tuhh_day_04_dyninit_s56p170 \
    /work/configs/mcd_hhs_os1_imuint_off01.yaml 56.170 2.0 A mapping_exp
run_one data/mcd/tuhh_day_04_os1  tuhh_day_04_dyninit_s56p170 \
    /work/configs/mcd_hhs_os1_imuint_off01.yaml 56.170 2.0 RED21 mapping_exp_redg
.venv/bin/python scripts/validate_dynamic_init.py \
    tuhh_day_04_dyninit_s56p170 data/mcd/tuhh_day_04_os1/os1.bag \
    --start-sec 56.170 --duration-sec 60

run_one data/mcd/ntu_day_10_os1 ntu_day_10_dyninit_s106p868 \
    /work/configs/mcd_atv_os1_imuint_off01.yaml 106.868 1.5 A mapping_exp
run_one data/mcd/ntu_day_10_os1 ntu_day_10_dyninit_s106p868 \
    /work/configs/mcd_atv_os1_imuint_off01.yaml 106.868 1.5 RED21 mapping_exp_redg
.venv/bin/python scripts/validate_dynamic_init.py \
    ntu_day_10_dyninit_s106p868 data/mcd/ntu_day_10_os1/os1.bag \
    --start-sec 106.868 --duration-sec 60

echo "DYNAMIC_INIT_PILOT_DONE $(date '+%Y-%m-%d %H:%M:%S')"
