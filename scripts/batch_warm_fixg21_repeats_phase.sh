#!/usr/bin/env bash
# Replicate the matched 23D->21D switch and vary the periodic-dropout phase.
# Experiments are strictly serial. The first shifted pair is a structural gate:
# no remaining run starts unless its frame/timestamp/prefix/DoF/hash checks pass.
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
echo "matched WarmFixG21 replication and dropout-phase audit" > "$CHAIN_LOCK/what"
trap cleanup_lock EXIT INT TERM

ATV=/work/configs/mcd_atv_os1_imuint_off01.yaml
HHS=/work/configs/mcd_hhs_os1_imuint_off01.yaml

make_phase_bag() {
    local source=$1 destination=$2 mode=$3 start=$4
    if [ -f "$destination" ]; then
        echo "== skip existing bag: $destination"
        return 0
    fi
    local partial="${destination}.partial.$$"
    .venv/bin/python scripts/degrade_bag.py "$source" "$partial" "$mode" \
        --drop-start-sec "$start"
    mv "$partial" "$destination"
}

run_one() {
    local seq=$1 bag=$2 config=$3 run_name=$4 trigger=${5:--1}
    local run_dir="results/$seq/$run_name"
    if [ -f "$run_dir/.complete" ]; then
        echo "== skip completed: $seq/$run_name"
        return 0
    fi
    if [ -f "$run_dir/state_log.csv" ]; then
        echo "Refusing to reuse unmarked state_log: $run_dir" >&2
        exit 4
    fi
    echo "== start: $seq/$run_name $(date '+%Y-%m-%d %H:%M:%S')"
    if [ "$trigger" = "-1" ]; then
        ./scripts/run_experiment.sh A "$bag" -c "$config" \
            -x configs/exp_tuning.yaml -n "$run_name" -r 1.5 -p
    else
        ./scripts/run_experiment.sh A "$bag" -c "$config" \
            -x configs/exp_tuning.yaml -n "$run_name" -r 1.5 -p \
            -U "$trigger" -J conditional
    fi
    touch "$run_dir/.complete"
    echo "== done: $seq/$run_name $(date '+%Y-%m-%d %H:%M:%S')"
}

validate_pair() {
    local seq=$1 online=$2 warm=$3 gap=$4 trigger=$5 gap_mode=${6:-target}
    local gap_arg=--gap-s
    if [ "$gap_mode" = "max" ]; then
        gap_arg=--max-gap-s
    fi
    .venv/bin/python scripts/validate_warm_fixg21.py "$seq" \
        --online "$online" --warm "$warm" "$gap_arg" "$gap" \
        --trigger-s "$trigger" --projection conditional
}

make_phase_bag data/mcd/ntu_day_10_os1/os1.bag \
    data/mcd/degraded/ntu_day_10_drop3x20_s12.bag drop3x20 12
make_phase_bag data/mcd/ntu_day_10_os1/os1.bag \
    data/mcd/degraded/ntu_day_10_drop3x20_s22.bag drop3x20 22
make_phase_bag data/mcd/tuhh_day_04_os1/os1.bag \
    data/mcd/degraded/tuhh_day_04_drop5x20_s12.bag drop5x20 12
make_phase_bag data/mcd/tuhh_day_04_os1/os1.bag \
    data/mcd/degraded/tuhh_day_04_drop5x20_s22.bag drop5x20 22

# Structural gate: one new phase pair must pass before the queue continues.
run_one ntu_day_10_drop3x20_s12 data/mcd/degraded/ntu_day_10_drop3x20_s12.bag \
    "$ATV" A_warm21
run_one ntu_day_10_drop3x20_s12 data/mcd/degraded/ntu_day_10_drop3x20_s12.bag \
    "$ATV" WarmFixG21C 12
validate_pair ntu_day_10_drop3x20_s12 A_warm21 WarmFixG21C 3 12

# Original trigger/phase: add two repeats to each clean/dropout cell.
for repeat in r2 r3; do
    run_one ntu_day_10_os1 data/mcd/ntu_day_10_os1 "$ATV" "A_warm21_${repeat}"
    run_one ntu_day_10_os1 data/mcd/ntu_day_10_os1 "$ATV" "WarmFixG21C_${repeat}" 17
    validate_pair ntu_day_10_os1 "A_warm21_${repeat}" "WarmFixG21C_${repeat}" 0.02 17 max

    run_one ntu_day_10_drop3x20 data/mcd/ntu_day_10_drop3x20 "$ATV" "A_warm21_${repeat}"
    run_one ntu_day_10_drop3x20 data/mcd/ntu_day_10_drop3x20 "$ATV" "WarmFixG21C_${repeat}" 17
    validate_pair ntu_day_10_drop3x20 "A_warm21_${repeat}" "WarmFixG21C_${repeat}" 3 17

    run_one tuhh_day_04_os1 data/mcd/tuhh_day_04_os1 "$HHS" "A_warm21_${repeat}"
    run_one tuhh_day_04_os1 data/mcd/tuhh_day_04_os1 "$HHS" "WarmFixG21C_${repeat}" 15
    validate_pair tuhh_day_04_os1 "A_warm21_${repeat}" "WarmFixG21C_${repeat}" 0.02 15 max

    run_one tuhh_day_04_drop5x20 data/mcd/tuhh_day_04_drop5x20 "$HHS" "A_warm21_${repeat}"
    run_one tuhh_day_04_drop5x20 data/mcd/tuhh_day_04_drop5x20 "$HHS" "WarmFixG21C_${repeat}" 15
    validate_pair tuhh_day_04_drop5x20 "A_warm21_${repeat}" "WarmFixG21C_${repeat}" 5 15
done

# Shifted phases. Online clean is trigger-independent and is reused only as a
# deterministic control; each clean Warm branch still switches at the matched time.
for start in 12 22; do
    run_one ntu_day_10_os1 data/mcd/ntu_day_10_os1 "$ATV" "WarmFixG21C_s${start}" "$start"
    validate_pair ntu_day_10_os1 A_warm21 "WarmFixG21C_s${start}" 0.02 "$start" max
    if [ "$start" != "12" ]; then
        seq="ntu_day_10_drop3x20_s${start}"
        bag="data/mcd/degraded/${seq}.bag"
        run_one "$seq" "$bag" "$ATV" A_warm21
        run_one "$seq" "$bag" "$ATV" WarmFixG21C "$start"
        validate_pair "$seq" A_warm21 WarmFixG21C 3 "$start"
    fi

    run_one tuhh_day_04_os1 data/mcd/tuhh_day_04_os1 "$HHS" "WarmFixG21C_s${start}" "$start"
    validate_pair tuhh_day_04_os1 A_warm21 "WarmFixG21C_s${start}" 0.02 "$start" max
    seq="tuhh_day_04_drop5x20_s${start}"
    bag="data/mcd/degraded/${seq}.bag"
    run_one "$seq" "$bag" "$HHS" A_warm21
    run_one "$seq" "$bag" "$HHS" WarmFixG21C "$start"
    validate_pair "$seq" A_warm21 WarmFixG21C 5 "$start"
done

.venv/bin/python scripts/audit_sleep.py
echo "WARM_FIXG21_REPEATS_PHASE_DONE $(date '+%Y-%m-%d %H:%M:%S')"
