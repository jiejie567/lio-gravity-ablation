#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "$0")/.." && pwd)
CHAIN_LOCK="$PROJECT_ROOT/.chain.lock"
if ! mkdir "$CHAIN_LOCK" 2>/dev/null; then
    echo "another batch holds $CHAIN_LOCK" >&2
    exit 3
fi
trap 'rmdir "$CHAIN_LOCK" 2>/dev/null || true' EXIT INT TERM

for repeat in r2 r3; do
    output="results/liosam_direction_repeats/mcd_tuhh_day04_drop3x20/FG-BA_off_${repeat}"
    if [[ -f "$PROJECT_ROOT/$output/state_log.csv" ]] && \
       rg -q '^finished_at=' "$PROJECT_ROOT/$output/run_meta.txt"; then
        echo "skip completed $output"
        continue
    fi
    "$PROJECT_ROOT/scripts/run_liosam_mcd_gravity_direction.sh" \
        FG-BA handheld data/mcd/degraded/tuhh_day_04_drop3x20.bag \
        data/mcd/tuhh_day_04/vn200.bag "$output" 0 0 187 0.25
    "$PROJECT_ROOT/.venv/bin/python" \
        "$PROJECT_ROOT/scripts/validate_liosam_direction_repeat.py" \
        "$PROJECT_ROOT/results/liosam_direction_dropout/mcd_tuhh_day04_drop3x20/FG-BA_off" \
        "$PROJECT_ROOT/$output"
done
