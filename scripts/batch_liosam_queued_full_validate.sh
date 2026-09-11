#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "$0")/.." && pwd)
CHAIN_LOCK="$PROJECT_ROOT/.chain.lock"
if ! mkdir "$CHAIN_LOCK" 2>/dev/null; then
    echo "another batch holds $CHAIN_LOCK" >&2
    exit 3
fi
trap 'rmdir "$CHAIN_LOCK" 2>/dev/null || true' EXIT INT TERM

ROOT=results/liosam_throughput/mcd_tuhh_day_04_queued
for variant in FG-BA FG-B0; do
    output="$PROJECT_ROOT/$ROOT/$variant"
    if [[ -f "$output/state_log.csv" && -f "$output/odometry.csv" ]] && \
       rg -q '^finished_at=' "$output/run_meta.txt"; then
        echo "skip completed $variant"
        continue
    fi
    "$PROJECT_ROOT/scripts/run_liosam_mcd_ablation.sh" \
        "$variant" handheld \
        data/mcd/tuhh_day_04/os1.bag data/mcd/tuhh_day_04/vn200.bag \
        "$ROOT/$variant" 0 187 0.5
done

"$PROJECT_ROOT/.venv/bin/python" - "$PROJECT_ROOT/$ROOT" <<'PY'
import csv, sys
from pathlib import Path
root = Path(sys.argv[1])
times = {}
for variant in ("FG-BA", "FG-B0"):
    with (root / variant / "odometry.csv").open(newline="") as handle:
        times[variant] = [row["%time"] for row in csv.DictReader(handle)]
counts = {key: len(value) for key, value in times.items()}
if times["FG-BA"] != times["FG-B0"]:
    raise SystemExit(f"FAIL: queued full-length timestamp gate: {counts}")
print(f"LIO-SAM queued full-length throughput gate: PASS ({counts['FG-BA']} timestamps)")
PY
