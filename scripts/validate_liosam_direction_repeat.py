#!/usr/bin/env python3
"""Admission gate for one repeated LIO-SAM gravity-direction run."""

from __future__ import annotations

import csv
import hashlib
import sys
from pathlib import Path


FATAL = ("Large velocity", "Large bias", "IndeterminateSystemException", "REQUIRED process")


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def meta(path: Path) -> dict[str, str]:
    return dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)


def sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} <reference-run> <repeat-run>", file=sys.stderr)
        return 2
    reference, repeat = (Path(value).resolve() for value in sys.argv[1:])
    project = Path(__file__).resolve().parent.parent
    metadata: list[dict[str, str]] = []
    for run in (reference, repeat):
        required = ("state_log.csv", "odometry.csv", "run_meta.txt", "launch.log")
        if not all((run / name).is_file() for name in required):
            raise RuntimeError(f"{run}: missing output")
        text = (run / "launch.log").read_text(errors="replace")
        if any(marker in text for marker in FATAL):
            raise RuntimeError(f"{run}: fatal/reset marker")
        values = meta(run / "run_meta.txt")
        metadata.append(values)
        if "finished_at" not in values or values.get("rate") != "0.25":
            raise RuntimeError(f"{run}: incomplete metadata or wrong rate")
        binary = project / "liosam_ws/devel/lib/lio_sam" / values["imu_node"]
        if sha1(binary) != values.get("binary_sha1"):
            raise RuntimeError(f"{run}: binary hash mismatch")

    modes = {values.get("gravity_direction_mode") for values in metadata}
    if len(modes) != 1 or modes.pop() not in {"ON", "OFF"}:
        raise RuntimeError("reference/repeat direction modes differ")
    enabled = metadata[0]["gravity_direction_mode"] == "ON"
    if enabled and not all((run / "gravity_direction.csv").is_file() for run in (reference, repeat)):
        raise RuntimeError("enabled repeat is missing direction log")

    reference_state, repeat_state = rows(reference / "state_log.csv"), rows(repeat / "state_log.csv")
    reference_odom, repeat_odom = rows(reference / "odometry.csv"), rows(repeat / "odometry.csv")
    reference_factor = rows(reference / "gravity_direction.csv") if enabled else []
    repeat_factor = rows(repeat / "gravity_direction.csv") if enabled else []
    expected = (len(reference_state), len(reference_odom), len(reference_factor))
    observed = (len(repeat_state), len(repeat_odom), len(repeat_factor))
    if observed != expected or (enabled and expected[0] != expected[2]):
        raise RuntimeError(f"frame-count gate failed: reference={expected}, repeat={observed}")
    if [row["timestamp"] for row in repeat_state] != [row["timestamp"] for row in reference_state]:
        raise RuntimeError("state timestamps differ")
    if [row["%time"] for row in repeat_odom] != [row["%time"] for row in reference_odom]:
        raise RuntimeError("odometry timestamps differ")
    if enabled and [row["timestamp"] for row in repeat_factor] != [row["timestamp"] for row in reference_factor]:
        raise RuntimeError("factor timestamps differ")
    print("LIO-SAM direction repeat validation: PASS")
    print(f"state/odometry/factor rows: {observed}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
