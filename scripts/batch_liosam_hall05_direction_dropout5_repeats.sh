#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "$0")/.." && pwd)
CHAIN_LOCK="$PROJECT_ROOT/.chain.lock"
ROOT_REL=results/liosam_direction_dropout/m2dgr_hall05_drop5x20
BAG_REL=data/m2dgr/degraded/hall05_drop5x20.bag
SIGMA_S2=0.03490658503988659

if ! mkdir "$CHAIN_LOCK" 2>/dev/null; then
    echo "another batch holds $CHAIN_LOCK" >&2
    exit 3
fi
trap 'rmdir "$CHAIN_LOCK" 2>/dev/null || true' EXIT INT TERM

run_cell()
{
    local variant=$1
    local level=$2
    local repeat=$3
    local sigma=0
    if [[ "$level" = s2 ]]; then
        sigma=$SIGMA_S2
    fi
    local output="$PROJECT_ROOT/$ROOT_REL/${variant}_${level}_${repeat}"
    if [[ -f "$output/state_log.csv" && -f "$output/odometry.csv" && \
          -f "$output/run_meta.txt" ]] && rg -q '^finished_at=' "$output/run_meta.txt"; then
        echo "skip completed ${variant}_${level}_${repeat}"
        return
    fi
    if [[ -e "$output" ]]; then
        echo "partial output exists; inspect and remove it before resuming: $output" >&2
        exit 2
    fi
    "$PROJECT_ROOT/scripts/run_liosam_gravity_direction.sh" \
        "$variant" "$BAG_REL" "$ROOT_REL/${variant}_${level}_${repeat}" \
        "$sigma" 0 400 0.5
}

# The first repeat is the preregistered structural-validation round.  The
# validator must pass before the remaining repeats are allowed to start.
for variant in FG-BA GE-BA; do
    for level in off s2; do
        run_cell "$variant" "$level" r1
    done
done
"$PROJECT_ROOT/.venv/bin/python" \
    "$PROJECT_ROOT/scripts/validate_liosam_hall05_direction_dropout.py" \
    "$PROJECT_ROOT/$ROOT_REL" r1

for repeat in r2 r3; do
    for variant in FG-BA GE-BA; do
        for level in off s2; do
            run_cell "$variant" "$level" "$repeat"
        done
    done
done
"$PROJECT_ROOT/.venv/bin/python" \
    "$PROJECT_ROOT/scripts/validate_liosam_hall05_direction_dropout.py" \
    "$PROJECT_ROOT/$ROOT_REL" r1 r2 r3

