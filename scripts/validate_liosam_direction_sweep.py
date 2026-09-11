#!/usr/bin/env python3
"""Structural admission gate for LIO-SAM gravity-direction sweeps."""

from __future__ import annotations

import argparse
import csv
import hashlib
import math
import statistics
from pathlib import Path


LEVEL_SIGMAS = {
    "off": 0.0,
    "s0p5": math.radians(0.5),
    "s2": math.radians(2.0),
    "s5": math.radians(5.0),
}
VARIANTS = ("FG-BA", "GE-BA")
FATAL_MARKERS = (
    "IndeterminateSystemException",
    "REQUIRED process",
    "process has died",
    "Large bias",
    "Large velocity",
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


def vector(row: dict[str, str], fields: tuple[str, str, str]) -> tuple[float, ...]:
    return tuple(float(row[field]) for field in fields)


def max_departure(rows: list[dict[str, str]], fields: tuple[str, str, str]) -> float:
    first = vector(rows[0], fields)
    return max(
        math.sqrt(sum((value - origin) ** 2 for value, origin in zip(vector(row, fields), first)))
        for row in rows
    )


def gravity_span(rows: list[dict[str, str]]) -> float:
    fields = ("gx", "gy", "gz")
    first = vector(rows[0], fields)
    first_norm = math.sqrt(sum(value * value for value in first))
    maximum = 0.0
    for row in rows:
        current = vector(row, fields)
        norm = math.sqrt(sum(value * value for value in current))
        cosine = sum(a * b for a, b in zip(first, current)) / (first_norm * norm)
        maximum = max(
            maximum,
            math.degrees(math.acos(max(-1.0, min(1.0, cosine)))),
        )
    return maximum


def expected_node(variant: str, enabled: bool) -> str:
    if enabled:
        return (
            "lio_sam_imuPreintegration_fg_ba_gdir"
            if variant == "FG-BA"
            else "lio_sam_imuPreintegration_ge_ba_gdir"
        )
    return (
        "lio_sam_imuPreintegration"
        if variant == "FG-BA"
        else "lio_sam_imuPreintegration_ge_ba"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument(
        "--levels", default="off,s0p5,s2,s5",
        help="comma-separated subset of off,s0p5,s2,s5",
    )
    parser.add_argument("--max-age", type=float, default=0.05)
    args = parser.parse_args()

    levels = tuple(args.levels.split(","))
    unknown = set(levels) - set(LEVEL_SIGMAS)
    if unknown or "off" not in levels:
        fail(f"invalid levels (must include off): {levels}")

    root = args.root.resolve()
    project = Path(__file__).resolve().parent.parent
    states: dict[str, list[dict[str, str]]] = {}
    odometry: dict[str, list[dict[str, str]]] = {}
    direction_summary: dict[str, tuple[int, float, float, float]] = {}
    rates: dict[str, float] = {}
    datasets: set[str] = set()

    for variant in VARIANTS:
        for level in levels:
            run_name = f"{variant}_{level}"
            run = root / run_name
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
            odometry_rows = read_csv(run / "odometry.csv")
            if not state_rows or not odometry_rows:
                fail(f"{run_name}: empty state or odometry output")
            if {row["variant"] for row in state_rows} != {variant}:
                fail(f"{run_name}: wrong state variant label")
            states[run_name] = state_rows
            odometry[run_name] = odometry_rows

            meta = read_meta(run / "run_meta.txt")
            enabled = level != "off"
            sigma = float(meta.get("gravity_direction_sigma_rad", "nan"))
            expected_sigma = LEVEL_SIGMAS[level]
            if not math.isclose(sigma, expected_sigma, rel_tol=0.0, abs_tol=1e-14):
                fail(f"{run_name}: sigma {sigma} != {expected_sigma}")
            if meta.get("gravity_direction_mode") != ("ON" if enabled else "OFF"):
                fail(f"{run_name}: direction-mode metadata mismatch")
            if meta.get("variant") != variant or meta.get("imu_node") != expected_node(variant, enabled):
                fail(f"{run_name}: variant/binary metadata mismatch")
            if "finished_at" not in meta or meta.get("omp_num_threads") != "1":
                fail(f"{run_name}: incomplete or nondeterministic metadata")
            rates[run_name] = float(meta.get("rate", "nan"))
            datasets.add(meta.get("dataset", ""))

            binary = project / "liosam_ws/devel/lib/lio_sam" / meta["imu_node"]
            mapping = project / "liosam_ws/devel/lib/lio_sam/lio_sam_mapOptmization"
            launch = project / meta["launch_file"]
            if sha1(binary) != meta.get("binary_sha1"):
                fail(f"{run_name}: IMU binary SHA-1 mismatch")
            if sha1(mapping) != meta.get("mapping_binary_sha1"):
                fail(f"{run_name}: mapping binary SHA-1 mismatch")
            if sha1(launch) != meta.get("launch_sha1"):
                fail(f"{run_name}: launch SHA-1 mismatch")
            if meta.get("dataset") == "mcd":
                calibration_name = (
                    "atv_calib_file" if meta.get("setup") == "atv"
                    else "handheld_calib_file"
                )
                calibration = project / "data/mcd/calib" / calibration_name
                if sha1(calibration) != meta.get("calibration_sha1"):
                    fail(f"{run_name}: calibration SHA-1 mismatch")

            direction_path = run / "gravity_direction.csv"
            direction_rows = read_csv(direction_path) if direction_path.is_file() else []
            if not enabled:
                if direction_rows:
                    fail(f"{run_name}: disabled factor produced rows")
                continue
            if len(direction_rows) != len(state_rows):
                fail(f"{run_name}: factor/state count mismatch")
            indices = [int(row["factor_index"]) for row in direction_rows]
            if indices != list(range(1, len(direction_rows) + 1)):
                fail(f"{run_name}: non-contiguous factor indices")
            ages = [float(row["measurement_age_s"]) for row in direction_rows]
            pre = [float(row["pre_residual_deg"]) for row in direction_rows]
            post = [float(row["post_residual_deg"]) for row in direction_rows]
            if not all(math.isfinite(value) for value in ages + pre + post):
                fail(f"{run_name}: non-finite direction instrumentation")
            if min(ages) < -1e-9 or max(ages) > args.max_age:
                fail(f"{run_name}: direction measurement age out of range")
            if statistics.median(pre) > 30.0 or max(pre) > 90.0:
                fail(f"{run_name}: likely quaternion sign/frame mismatch")
            if post[0] > pre[0] or statistics.median(post) > 1.05 * statistics.median(pre):
                fail(f"{run_name}: factor does not pull toward observation")
            direction_summary[run_name] = (
                len(direction_rows), statistics.median(pre),
                statistics.median(post), max(ages),
            )

    if len(datasets) != 1 or "" in datasets:
        fail(f"mixed or missing dataset metadata: {datasets}")
    if len(set(rates.values())) != 1 or not (0.0 < next(iter(rates.values())) <= 0.5):
        fail(f"playback-rate gate failed: {rates}")
    state_counts = {name: len(rows) for name, rows in states.items()}
    odometry_counts = {name: len(rows) for name, rows in odometry.items()}
    if len(set(state_counts.values())) != 1:
        fail(f"state-frame zero-tolerance gate failed: {state_counts}")
    if len(set(odometry_counts.values())) != 1:
        fail(f"odometry-frame zero-tolerance gate failed: {odometry_counts}")

    reference_state_times = [row["timestamp"] for row in states[f"FG-BA_{levels[0]}"]]
    reference_odom_times = [row["%time"] for row in odometry[f"FG-BA_{levels[0]}"]]
    for run_name, rows in states.items():
        if [row["timestamp"] for row in rows] != reference_state_times:
            fail(f"{run_name}: state timestamps differ")
    for run_name, rows in odometry.items():
        if [row["%time"] for row in rows] != reference_odom_times:
            fail(f"{run_name}: odometry timestamps differ")

    gravity_norms = [
        math.sqrt(sum(value * value for value in vector(row, ("gx", "gy", "gz"))))
        for rows in states.values() for row in rows
    ]
    norm_error = max(abs(value - gravity_norms[0]) for value in gravity_norms)
    if norm_error > 1e-10:
        fail(f"gravity magnitude changed: {norm_error:.3e}")
    for run_name, rows in states.items():
        span = gravity_span(rows)
        if run_name.startswith("FG-BA") and span > 1e-9:
            fail(f"{run_name}: fixed gravity moved")
        if run_name.startswith("GE-BA") and span < 1e-3:
            fail(f"{run_name}: online gravity did not move")
        if max_departure(rows, ("bax", "bay", "baz")) < 1e-6:
            fail(f"{run_name}: online accelerometer bias did not move")
        if max_departure(rows, ("bgx", "bgy", "bgz")) < 1e-7:
            fail(f"{run_name}: online gyroscope bias did not move")

    print("LIO-SAM gravity-direction sweep structural validation: PASS")
    print(f"dataset: {next(iter(datasets))}")
    print(f"state/odometry rows per run: {next(iter(state_counts.values()))}/{next(iter(odometry_counts.values()))}")
    print(f"gravity norm: {gravity_norms[0]:.12f} (max error {norm_error:.2e})")
    for run_name in sorted(direction_summary):
        count, pre, post, age = direction_summary[run_name]
        print(f"{run_name}: factors={count}, median={pre:.4f}->{post:.4f} deg, max_age={age:.6f} s")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as error:
        print(f"FAIL: {error}")
        raise SystemExit(1)
