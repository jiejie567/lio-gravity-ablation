#!/usr/bin/env python3
"""Structural gate for the LIO-SAM gravity-direction 2x2 pilot."""

from __future__ import annotations

import csv
import hashlib
import math
import statistics
import sys
from pathlib import Path


RUNS = ("FG-BA_D0", "FG-BA_D1", "GE-BA_D0", "GE-BA_D1")
FATAL_MARKERS = (
    "IndeterminateSystemException",
    "REQUIRED process",
    "process has died",
    "Large bias",
    "Large velocity",
)
STATE_NUMERIC_FIELDS = (
    "px", "py", "pz", "vx", "vy", "vz",
    "bax", "bay", "baz", "bgx", "bgy", "bgz", "gx", "gy", "gz",
)


def fail(message: str) -> None:
    raise RuntimeError(message)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def read_meta(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            result[key] = value
    return result


def sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def gravity_span(rows: list[dict[str, str]]) -> float:
    first = tuple(float(rows[0][field]) for field in ("gx", "gy", "gz"))
    first_norm = math.sqrt(sum(value * value for value in first))
    maximum = 0.0
    for row in rows:
        current = tuple(float(row[field]) for field in ("gx", "gy", "gz"))
        current_norm = math.sqrt(sum(value * value for value in current))
        cosine = sum(a * b for a, b in zip(first, current)) / (
            first_norm * current_norm
        )
        maximum = max(
            maximum,
            math.degrees(math.acos(max(-1.0, min(1.0, cosine)))),
        )
    return maximum


def max_ba_departure(rows: list[dict[str, str]]) -> float:
    fields = ("bax", "bay", "baz")
    first = tuple(float(rows[0][field]) for field in fields)
    return max(
        math.sqrt(
            sum((float(row[field]) - origin) ** 2 for field, origin in zip(fields, first))
        )
        for row in rows
    )


def verify_off_repeatability(
    project: Path, variant: str, rows: list[dict[str, str]]
) -> float:
    reference_path = (
        project / "quarantine/liosam_gravity_direction_runtime_switch_20260825"
        / f"{variant}_D0" / "state_log.csv"
    )
    if not reference_path.is_file():
        fail(f"{variant}_D0: missing independent short-run repeat {reference_path}")
    reference = {row["timestamp"]: row for row in read_csv(reference_path)}
    maximum = 0.0
    for row in rows:
        reference_row = reference.get(row["timestamp"])
        if reference_row is None:
            fail(f"{variant}_D0: timestamp absent from independent repeat")
        for field in STATE_NUMERIC_FIELDS:
            maximum = max(
                maximum,
                abs(float(row[field]) - float(reference_row[field])),
            )
    if maximum > 1e-12:
        fail(f"{variant}_D0: short-run repeat mismatch (max {maximum:.3e})")
    return maximum


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <pilot-root>", file=sys.stderr)
        return 2

    root = Path(sys.argv[1]).resolve()
    project = Path(__file__).resolve().parent.parent
    states: dict[str, list[dict[str, str]]] = {}
    directions: dict[str, list[dict[str, str]]] = {}
    odometry_counts: dict[str, int] = {}

    for run_name in RUNS:
        run = root / run_name
        variant, direction_mode = run_name.split("_")
        required = (
            run / "state_log.csv",
            run / "odometry.csv",
            run / "run_meta.txt",
            run / "launch.log",
        )
        if not all(path.is_file() for path in required):
            fail(f"{run_name}: missing required output")

        launch_text = (run / "launch.log").read_text(errors="replace")
        for marker in FATAL_MARKERS:
            if marker in launch_text:
                fail(f"{run_name}: fatal marker in launch.log: {marker}")

        state_rows = read_csv(run / "state_log.csv")
        direction_path = run / "gravity_direction.csv"
        direction_rows = read_csv(direction_path) if direction_path.is_file() else []
        odometry_rows = read_csv(run / "odometry.csv")
        if not state_rows or not odometry_rows:
            fail(f"{run_name}: empty state or odometry output")
        if {row["variant"] for row in state_rows} != {variant}:
            fail(f"{run_name}: wrong state variant label")
        states[run_name] = state_rows
        directions[run_name] = direction_rows
        odometry_counts[run_name] = len(odometry_rows)

        meta = read_meta(run / "run_meta.txt")
        expected_mode = "ON" if direction_mode == "D1" else "OFF"
        sigma = float(meta.get("gravity_direction_sigma_rad", "nan"))
        if meta.get("variant") != variant or meta.get("gravity_direction_mode") != expected_mode:
            fail(f"{run_name}: metadata label mismatch")
        if (direction_mode == "D1") != (sigma > 0.0):
            fail(f"{run_name}: sigma does not match direction mode")
        if "finished_at" not in meta or meta.get("omp_num_threads") != "1":
            fail(f"{run_name}: incomplete or nondeterministic metadata")
        binary = project / "liosam_ws/devel/lib/lio_sam" / meta["imu_node"]
        mapping = project / "liosam_ws/devel/lib/lio_sam/lio_sam_mapOptmization"
        launch = project / meta["launch_file"]
        if sha1(binary) != meta.get("binary_sha1"):
            fail(f"{run_name}: IMU binary SHA-1 mismatch")
        if sha1(mapping) != meta.get("mapping_binary_sha1"):
            fail(f"{run_name}: mapping binary SHA-1 mismatch")
        if sha1(launch) != meta.get("launch_sha1"):
            fail(f"{run_name}: launch SHA-1 mismatch")

    state_counts = {name: len(rows) for name, rows in states.items()}
    if len(set(state_counts.values())) != 1:
        fail(f"state-frame zero-tolerance gate failed: {state_counts}")
    if len(set(odometry_counts.values())) != 1:
        fail(f"odometry-frame zero-tolerance gate failed: {odometry_counts}")
    reference_times = [row["timestamp"] for row in states[RUNS[0]]]
    for run_name in RUNS[1:]:
        if [row["timestamp"] for row in states[run_name]] != reference_times:
            fail(f"{run_name}: correction timestamps differ")

    for run_name in ("FG-BA_D0", "GE-BA_D0"):
        if directions[run_name]:
            fail(f"{run_name}: disabled direction factor was added")

    for run_name in ("FG-BA_D1", "GE-BA_D1"):
        rows = directions[run_name]
        if len(rows) != len(states[run_name]):
            fail(
                f"{run_name}: factor/state count mismatch "
                f"({len(rows)} != {len(states[run_name])})"
            )
        indices = [int(row["factor_index"]) for row in rows]
        if indices != list(range(1, len(rows) + 1)):
            fail(f"{run_name}: factor indices are not contiguous")
        ages = [float(row["measurement_age_s"]) for row in rows]
        pre = [float(row["pre_residual_deg"]) for row in rows]
        post = [float(row["post_residual_deg"]) for row in rows]
        if not all(math.isfinite(value) for value in ages + pre + post):
            fail(f"{run_name}: non-finite direction instrumentation")
        if min(ages) < -1e-9 or max(ages) > 0.05:
            fail(f"{run_name}: IMU direction measurement age out of range")
        if statistics.median(pre) > 30.0 or max(pre) > 90.0:
            fail(f"{run_name}: likely quaternion sign/frame mismatch")
        if post[0] > pre[0] or statistics.median(post) > 1.05 * statistics.median(pre):
            fail(f"{run_name}: direction factor does not pull toward its observation")

    for run_name, rows in states.items():
        span = gravity_span(rows)
        if run_name.startswith("FG-") and span > 1e-9:
            fail(f"{run_name}: fixed gravity moved by {span:.3e} deg")
        if run_name.startswith("GE-") and span < 1e-3:
            fail(f"{run_name}: online gravity did not move")
        if max_ba_departure(rows) < 1e-6:
            fail(f"{run_name}: online accelerometer bias did not move")

    equivalence = {
        variant: verify_off_repeatability(project, variant, states[f"{variant}_D0"])
        for variant in ("FG-BA", "GE-BA")
    }

    print("LIO-SAM gravity-direction pilot structural validation: PASS")
    print(f"state rows per run: {next(iter(state_counts.values()))}")
    print(f"odometry rows per run: {next(iter(odometry_counts.values()))}")
    for run_name in ("FG-BA_D1", "GE-BA_D1"):
        rows = directions[run_name]
        pre = [float(row["pre_residual_deg"]) for row in rows]
        post = [float(row["post_residual_deg"]) for row in rows]
        ages = [float(row["measurement_age_s"]) for row in rows]
        print(
            f"{run_name}: factors={len(rows)}, median residual "
            f"{statistics.median(pre):.4f}->{statistics.median(post):.4f} deg, "
            f"max age={max(ages):.6f} s"
        )
    for variant, error in equivalence.items():
        print(f"{variant}_D0 independent-repeat max error: {error:.2e}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
