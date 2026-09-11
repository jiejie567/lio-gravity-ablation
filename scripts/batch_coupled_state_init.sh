#!/usr/bin/env bash
# Paired initialization experiment for the g--ba correction subspace.
# Runs are serial, re-entrant only for completed outputs, and outcome-locked.
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
echo "paired gravity--accelerometer-bias initialization" > "$CHAIN_LOCK/what"
trap cleanup_lock EXIT INT TERM

run_one() {
    local bag=$1 group=$2 config=$3 rate=$4 name=$5 angle=$6 ba=${7:-}
    local run_dir="results/$group/$name"
    if [ -f "$run_dir/state_log.csv" ]; then
        if [ -f "$run_dir/console.log" ] && rg -q "state_log 行数:" "$run_dir/console.log"; then
            echo "== skip completed: $group/$name"
            return 0
        fi
        echo "Refusing partial output: $run_dir (remove it explicitly before rerun)." >&2
        exit 4
    fi
    local cmd=(./scripts/run_experiment.sh A "$bag"
        -c "$config" -x configs/exp_tuning.yaml -q "$group"
        -u 60 -r "$rate" -p -n "$name" -L mapping_exp -e "$angle")
    if [ -n "$ba" ]; then
        cmd+=(-B "$ba")
    fi
    "${cmd[@]}"
}

analyze_group() {
    local group=$1 gt=$2
    shift 2
    .venv/bin/python scripts/analyze.py \
        --seq-dir "results/$group" \
        --runs base g_p2 gb_p2 g_m2 gb_m2 \
        --gt "$gt" --align-sec 10 --align-m 30 \
        --drift-win-m 50 --open-loop-min-dist 80 --est2body "$@"
}

E2B_ATV=(0.054216 -0.001058 -0.028667 0.999935 0.003587 -0.010854 0.003478 -0.999943 -0.010092 -0.010890 0.010054 -0.999890)
E2B_HHS=(0.042216 -0.019535 -0.026406 0.999914 -0.011356 -0.006635 -0.011166 -0.999545 0.028009 -0.006950 -0.027932 -0.999586)

# Validate the current Online/reduced build family before opening a new batch.
.venv/bin/python scripts/validate_reduced.py ntu_day_10_os1 tuhh_day_04_os1

# Structural pilot: no later cell starts until the positive vehicle triplet
# proves identical timestamps, the intended 2-degree tilt, exact online states,
# binary provenance, and cancellation of g - R ba at the boundary.
VEH_GROUP=ntu_day_10_coupledinit60
run_one data/mcd/ntu_day_10_os1 "$VEH_GROUP" \
    /work/configs/mcd_atv_os1_imuint_off01.yaml 1.5 base 0
run_one data/mcd/ntu_day_10_os1 "$VEH_GROUP" \
    /work/configs/mcd_atv_os1_imuint_off01.yaml 1.5 g_p2 2
veh_ba_plus="$(.venv/bin/python scripts/coupled_init_ba.py \
    "results/$VEH_GROUP/base/state_log.csv" 2)"
run_one data/mcd/ntu_day_10_os1 "$VEH_GROUP" \
    /work/configs/mcd_atv_os1_imuint_off01.yaml 1.5 gb_p2 2 "$veh_ba_plus"
.venv/bin/python scripts/validate_coupled_state_init.py "$VEH_GROUP" --partial

veh_ba_minus="$(.venv/bin/python scripts/coupled_init_ba.py \
    "results/$VEH_GROUP/base/state_log.csv" -2)"
run_one data/mcd/ntu_day_10_os1 "$VEH_GROUP" \
    /work/configs/mcd_atv_os1_imuint_off01.yaml 1.5 g_m2 -2
run_one data/mcd/ntu_day_10_os1 "$VEH_GROUP" \
    /work/configs/mcd_atv_os1_imuint_off01.yaml 1.5 gb_m2 -2 "$veh_ba_minus"
analyze_group "$VEH_GROUP" data/mcd/ntu_day_10/gt/pose_inW.csv "${E2B_ATV[@]}"
.venv/bin/python scripts/validate_coupled_state_init.py "$VEH_GROUP"

HHS_GROUP=tuhh_day_04_coupledinit60
run_one data/mcd/tuhh_day_04_os1 "$HHS_GROUP" \
    /work/configs/mcd_hhs_os1_imuint_off01.yaml 2.0 base 0
run_one data/mcd/tuhh_day_04_os1 "$HHS_GROUP" \
    /work/configs/mcd_hhs_os1_imuint_off01.yaml 2.0 g_p2 2
hhs_ba_plus="$(.venv/bin/python scripts/coupled_init_ba.py \
    "results/$HHS_GROUP/base/state_log.csv" 2)"
run_one data/mcd/tuhh_day_04_os1 "$HHS_GROUP" \
    /work/configs/mcd_hhs_os1_imuint_off01.yaml 2.0 gb_p2 2 "$hhs_ba_plus"
hhs_ba_minus="$(.venv/bin/python scripts/coupled_init_ba.py \
    "results/$HHS_GROUP/base/state_log.csv" -2)"
run_one data/mcd/tuhh_day_04_os1 "$HHS_GROUP" \
    /work/configs/mcd_hhs_os1_imuint_off01.yaml 2.0 g_m2 -2
run_one data/mcd/tuhh_day_04_os1 "$HHS_GROUP" \
    /work/configs/mcd_hhs_os1_imuint_off01.yaml 2.0 gb_m2 -2 "$hhs_ba_minus"
analyze_group "$HHS_GROUP" data/mcd/tuhh_day_04/gt/pose_inW.csv "${E2B_HHS[@]}"
.venv/bin/python scripts/validate_coupled_state_init.py "$HHS_GROUP"

.venv/bin/python scripts/collect_coupled_state_init.py
.venv/bin/python scripts/audit_sleep.py
echo "COUPLED_STATE_INIT_DONE $(date '+%Y-%m-%d %H:%M:%S')"
