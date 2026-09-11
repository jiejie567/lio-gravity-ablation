#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "$0")/.." && pwd)
CHAIN_LOCK="$PROJECT_ROOT/.chain.lock"
if ! mkdir "$CHAIN_LOCK" 2>/dev/null; then
    echo "another batch holds $CHAIN_LOCK" >&2
    exit 3
fi
trap 'rmdir "$CHAIN_LOCK" 2>/dev/null || true' EXIT INT TERM

ROOT=results/liosam_throughput/m2dgr_hall05_rate05
for variant in FG-BA FG-B0; do
    output="$PROJECT_ROOT/$ROOT/$variant"
    if [[ -f "$output/state_log.csv" && -f "$output/odometry.csv" ]] && \
       rg -q '^finished_at=' "$output/run_meta.txt"; then
        echo "skip completed $variant"
        continue
    fi
    "$PROJECT_ROOT/scripts/run_liosam_ablation.sh" \
        "$variant" data/m2dgr/hall_05/lidar_imu.bag \
        "$ROOT/$variant" 0 400 0.5
done

"$PROJECT_ROOT/.venv/bin/python" - "$PROJECT_ROOT/$ROOT" <<'PY'
import csv, sys
from pathlib import Path
root = Path(sys.argv[1])
times = {}
for variant in ("FG-BA", "FG-B0"):
    run = root / variant
    log = (run / "launch.log").read_text(errors="replace")
    if "Large velocity" in log or "Large bias" in log:
        raise SystemExit(f"FAIL: {variant} emitted an IMU reset")
    with (run / "odometry.csv").open(newline="") as handle:
        times[variant] = [row["%time"] for row in csv.DictReader(handle)]
counts = {key: len(value) for key, value in times.items()}
if times["FG-BA"] != times["FG-B0"]:
    raise SystemExit(f"FAIL: Hall05 timestamp gate: {counts}")
if counts["FG-BA"] < 1900:
    raise SystemExit(f"FAIL: Hall05 unexpectedly short: {counts}")
print(f"LIO-SAM Hall05 rate-0.5 gate: PASS ({counts['FG-BA']} timestamps, no resets)")
PY
