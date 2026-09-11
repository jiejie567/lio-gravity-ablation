#!/usr/bin/env python3
"""Structural admission gate for the LIO-SAM g/b_a 2x2 ablation."""

from __future__ import annotations

import csv
import hashlib
import math
import sys
from pathlib import Path


VARIANTS = ("FG-BA", "FG-B0", "GE-BA", "GE-B0")
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


def vec(row: dict[str, str], fields: tuple[str, str, str]) -> tuple[float, ...]:
    return tuple(float(row[field]) for field in fields)


def distance(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def max_departure(rows: list[dict[str, str]], fields: tuple[str, str, str]) -> float:
    origin = vec(rows[0], fields)
    return max(distance(vec(row, fields), origin) for row in rows)


def gravity_angle_span(rows: list[dict[str, str]]) -> float:
    first = vec(rows[0], ("gx", "gy", "gz"))
    first_norm = math.sqrt(sum(x * x for x in first))
    maximum = 0.0
    for row in rows:
        current = vec(row, ("gx", "gy", "gz"))
        norm = math.sqrt(sum(x * x for x in current))
        cosine = sum(x * y for x, y in zip(first, current)) / (first_norm * norm)
        angle = math.degrees(math.acos(max(-1.0, min(1.0, cosine))))
        maximum = max(maximum, angle)
    return maximum


def sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_meta(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            result[key] = value
    return result


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <validation-root>", file=sys.stderr)
        return 2

    root = Path(sys.argv[1]).resolve()
    project = Path(__file__).resolve().parent.parent
    states: dict[str, list[dict[str, str]]] = {}
    odometry_counts: dict[str, int] = {}
    playback_rates: dict[str, float] = {}

    for variant in VARIANTS:
        run = root / variant
        state_path = run / "state_log.csv"
        odometry_path = run / "odometry.csv"
        meta_path = run / "run_meta.txt"
        if not all(path.is_file() for path in (state_path, odometry_path, meta_path)):
            fail(f"{variant}: missing state, odometry, or metadata file")

        launch_text = (run / "launch.log").read_text(errors="replace")
        for marker in FATAL_MARKERS:
            if marker in launch_text:
                fail(f"{variant}: fatal marker in launch.log: {marker}")

        rows = read_csv(state_path)
        odometry = read_csv(odometry_path)
        if not rows or not odometry:
            fail(f"{variant}: empty output")
        if {row["variant"] for row in rows} != {variant}:
            fail(f"{variant}: state log contains a different variant label")
        states[variant] = rows
        odometry_counts[variant] = len(odometry)

        meta = read_meta(meta_path)
        if meta.get("variant") != variant or "finished_at" not in meta:
            fail(f"{variant}: incomplete metadata")
        binary = project / "liosam_ws/devel/lib/lio_sam" / meta["imu_node"]
        if sha1(binary) != meta.get("binary_sha1"):
            fail(f"{variant}: binary SHA-1 mismatch")
        mapping_binary = project / "liosam_ws/devel/lib/lio_sam/lio_sam_mapOptmization"
        if sha1(mapping_binary) != meta.get("mapping_binary_sha1"):
            fail(f"{variant}: mapping binary SHA-1 mismatch")
        launch_name = meta.get("launch_file")
        if not launch_name:
            launch_name = (
                "liosam_ws/src/LIO-SAM/launch/run_mcd_ablation.launch"
                if meta.get("dataset") == "mcd"
                else "liosam_ws/src/LIO-SAM/launch/run_m2dgr_ablation.launch"
            )
        if sha1(project / launch_name) != meta.get("launch_sha1"):
            fail(f"{variant}: launch SHA-1 mismatch")
        if meta.get("omp_num_threads") != "1":
            fail(f"{variant}: non-deterministic execution settings")
        playback_rates[variant] = float(meta.get("rate", "nan"))
        if meta.get("dataset") == "mcd":
            calibration_name = (
                "atv_calib_file" if meta.get("setup") == "atv"
                else "handheld_calib_file"
            )
            calibration = project / "data/mcd/calib" / calibration_name
            if sha1(calibration) != meta.get("calibration_sha1"):
                fail(f"{variant}: calibration SHA-1 mismatch")

    state_counts = {variant: len(rows) for variant, rows in states.items()}
    if len(set(playback_rates.values())) != 1 or not (0 < next(iter(playback_rates.values())) <= 0.5):
        fail(f"playback-rate gate failed: {playback_rates}")
    if len(set(state_counts.values())) != 1:
        fail(f"state-frame zero-tolerance gate failed: {state_counts}")
    if len(set(odometry_counts.values())) != 1:
        fail(f"odometry-frame zero-tolerance gate failed: {odometry_counts}")

    reference_times = [row["timestamp"] for row in states["FG-BA"]]
    for variant in VARIANTS[1:]:
        if [row["timestamp"] for row in states[variant]] != reference_times:
            fail(f"{variant}: correction timestamps differ from FG-BA")

    gravity_norms = []
    for rows in states.values():
        gravity_norms.extend(
            math.sqrt(sum(x * x for x in vec(row, ("gx", "gy", "gz"))))
            for row in rows
        )
    gravity_reference = gravity_norms[0]
    gravity_norm_error = max(abs(value - gravity_reference) for value in gravity_norms)
    if gravity_norm_error > 1e-10:
        fail(f"gravity norm is not fixed: max error {gravity_norm_error:.3e}")

    ba_departures = {
        variant: max_departure(rows, ("bax", "bay", "baz"))
        for variant, rows in states.items()
    }
    bg_departures = {
        variant: max_departure(rows, ("bgx", "bgy", "bgz"))
        for variant, rows in states.items()
    }
    gravity_spans = {
        variant: gravity_angle_span(rows) for variant, rows in states.items()
    }

    for variant in ("FG-B0", "GE-B0"):
        if ba_departures[variant] > 1e-12:
            fail(f"{variant}: fixed b_a moved by {ba_departures[variant]:.3e}")
    for variant in ("FG-BA", "GE-BA"):
        if ba_departures[variant] < 1e-6:
            fail(f"{variant}: online b_a did not move")
    for variant in ("FG-BA", "FG-B0"):
        if gravity_spans[variant] > 1e-9:
            fail(f"{variant}: fixed gravity direction moved")
    for variant in ("GE-BA", "GE-B0"):
        if gravity_spans[variant] < 1e-3:
            fail(f"{variant}: online gravity direction did not move")
    for variant in VARIANTS:
        if bg_departures[variant] < 1e-7:
            fail(f"{variant}: online b_g did not move")

    print("LIO-SAM ablation structural validation: PASS")
    print(f"state rows per variant: {next(iter(state_counts.values()))}")
    print(f"odometry rows per variant: {next(iter(odometry_counts.values()))}")
    print(f"gravity norm: {gravity_reference:.12f} (max error {gravity_norm_error:.2e})")
    for variant in VARIANTS:
        print(
            f"{variant}: delta_ba={ba_departures[variant]:.6g}, "
            f"delta_bg={bg_departures[variant]:.6g}, "
            f"gravity_span_deg={gravity_spans[variant]:.6g}"
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
