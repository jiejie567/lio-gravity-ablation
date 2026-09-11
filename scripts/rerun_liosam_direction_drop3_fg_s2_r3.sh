#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "$0")/.." && pwd)
CHAIN_LOCK="$PROJECT_ROOT/.chain.lock"
if ! mkdir "$CHAIN_LOCK" 2>/dev/null; then
    echo "another batch holds $CHAIN_LOCK" >&2
    exit 3
fi
trap 'rmdir "$CHAIN_LOCK" 2>/dev/null || true' EXIT INT TERM

output=results/liosam_direction_repeats/mcd_tuhh_day04_drop3x20/FG-BA_s2_r3
if [[ -e "$PROJECT_ROOT/$output" ]]; then
    echo "replication target already exists: $output" >&2
    exit 2
fi

"$PROJECT_ROOT/scripts/run_liosam_mcd_gravity_direction.sh" \
    FG-BA handheld data/mcd/degraded/tuhh_day_04_drop3x20.bag \
    data/mcd/tuhh_day_04/vn200.bag "$output" \
    0.03490658503988659 0 187 0.25
