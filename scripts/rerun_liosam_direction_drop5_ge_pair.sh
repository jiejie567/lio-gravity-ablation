#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "$0")/.." && pwd)
CHAIN_LOCK="$PROJECT_ROOT/.chain.lock"
if ! mkdir "$CHAIN_LOCK" 2>/dev/null; then
    echo "another batch holds $CHAIN_LOCK" >&2
    exit 3
fi
trap 'rmdir "$CHAIN_LOCK" 2>/dev/null || true' EXIT INT TERM

for level in off s2; do
    if [[ "$level" = off ]]; then
        sigma=0
    else
        sigma=0.03490658503988659
    fi
    output="results/liosam_direction_repeats/mcd_tuhh_day04_drop5x20/GE-BA_${level}_r2"
    if [[ -f "$PROJECT_ROOT/$output/state_log.csv" ]] && \
       rg -q '^finished_at=' "$PROJECT_ROOT/$output/run_meta.txt"; then
        echo "skip completed $output"
        continue
    fi
    "$PROJECT_ROOT/scripts/run_liosam_mcd_gravity_direction.sh" \
        GE-BA handheld data/mcd/degraded/tuhh_day_04_drop5x20.bag \
        data/mcd/tuhh_day_04/vn200.bag "$output" "$sigma" 0 187 0.25
    "$PROJECT_ROOT/.venv/bin/python" \
        "$PROJECT_ROOT/scripts/validate_liosam_direction_repeat.py" \
        "$PROJECT_ROOT/results/liosam_direction_dropout/mcd_tuhh_day04_drop5x20/GE-BA_${level}" \
        "$PROJECT_ROOT/$output"
done
