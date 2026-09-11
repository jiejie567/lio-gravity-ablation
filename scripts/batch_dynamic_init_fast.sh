#!/usr/bin/env bash
# Stronger natural-motion starts: true 23D Online vs true 21D FixG.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

.venv/bin/python scripts/select_fast_dynamic_init.py

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
echo "stronger-motion dynamic initialization" > "$CHAIN_LOCK/what"
trap cleanup_lock EXIT INT TERM

run_one() {
    local bag=$1 seq=$2 config=$3 start=$4 rate=$5 run=$6 launch=$7
    if [ -f "results/$seq/$run/state_log.csv" ]; then
        echo "== skip existing: $seq/$run"
        return 0
    fi
    ./scripts/run_experiment.sh A "$bag" \
        -c "$config" -x configs/exp_tuning.yaml \
        -S "$start" -u 60 -q "$seq" -r "$rate" -p \
        -n "$run" -L "$launch"
}

analyze_pair() {
    local seq=$1 gt=$2
    shift 2
    .venv/bin/python scripts/analyze.py \
        --seq-dir "results/$seq" --runs A RED21 --gt "$gt" \
        --align-sec 10 --align-m 30 --drift-win-m 50 \
        --open-loop-min-dist 80 --est2body "$@"
}

run_pair() {
    local bag=$1 seq=$2 config=$3 start=$4 rate=$5 bag_file=$6 gt=$7
    shift 7
    run_one "$bag" "$seq" "$config" "$start" "$rate" A mapping_exp
    run_one "$bag" "$seq" "$config" "$start" "$rate" RED21 mapping_exp_redg
    .venv/bin/python scripts/validate_dynamic_init.py "$seq" "$bag_file" \
        --start-sec "$start" --duration-sec 60
    analyze_pair "$seq" "$gt" "$@"
}

E2B_ATV=(0.054216 -0.001058 -0.028667 0.999935 0.003587 -0.010854 0.003478 -0.999943 -0.010092 -0.010890 0.010054 -0.999890)
E2B_HHS=(0.042216 -0.019535 -0.026406 0.999914 -0.011356 -0.006635 -0.011166 -0.999545 0.028009 -0.006950 -0.027932 -0.999586)

# First pair is the structural pilot.  No later pair starts unless it passes.
run_pair data/mcd/tuhh_day_04_os1 tuhh_day_04_fastinit_s70p572 \
    /work/configs/mcd_hhs_os1_imuint_off01.yaml 70.572 2.0 \
    data/mcd/tuhh_day_04_os1/os1.bag data/mcd/tuhh_day_04/gt/pose_inW.csv \
    "${E2B_HHS[@]}"

run_pair data/mcd/ntu_day_10_os1 ntu_day_10_fastinit_s130p072 \
    /work/configs/mcd_atv_os1_imuint_off01.yaml 130.072 1.5 \
    data/mcd/ntu_day_10_os1/os1.bag data/mcd/ntu_day_10/gt/pose_inW.csv \
    "${E2B_ATV[@]}"
run_pair data/mcd/tuhh_day_04_os1 tuhh_day_04_fastinit_s114p279 \
    /work/configs/mcd_hhs_os1_imuint_off01.yaml 114.279 2.0 \
    data/mcd/tuhh_day_04_os1/os1.bag data/mcd/tuhh_day_04/gt/pose_inW.csv \
    "${E2B_HHS[@]}"
run_pair data/mcd/ntu_day_10_os1 ntu_day_10_fastinit_s189p471 \
    /work/configs/mcd_atv_os1_imuint_off01.yaml 189.471 1.5 \
    data/mcd/ntu_day_10_os1/os1.bag data/mcd/ntu_day_10/gt/pose_inW.csv \
    "${E2B_ATV[@]}"

.venv/bin/python scripts/collect_dynamic_init_fast.py
.venv/bin/python scripts/audit_sleep.py
echo "DYNAMIC_INIT_FAST_DONE $(date '+%Y-%m-%d %H:%M:%S')"
