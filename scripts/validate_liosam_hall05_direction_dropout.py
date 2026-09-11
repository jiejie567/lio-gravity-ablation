#!/usr/bin/env python3
"""Validate the repeated Hall05 drop5x20 LIO-SAM direction-factor ablation."""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import math
import statistics
import subprocess
import sys
from collections import Counter
from pathlib import Path

from rosbags.rosbag1 import Reader


ROOT = Path(__file__).resolve().parent.parent
VARIANTS = ("FG-BA", "GE-BA")
LEVELS = ("off", "s2")
SIGMA_S2 = math.radians(2.0)
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


def gravity_span(rows: list[dict[str, str]]) -> float:
    first = tuple(float(rows[0][field]) for field in ("gx", "gy", "gz"))
    norm0 = math.sqrt(sum(value * value for value in first))
    maximum = 0.0
    for row in rows:
        current = tuple(float(row[field]) for field in ("gx", "gy", "gz"))
        norm = math.sqrt(sum(value * value for value in current))
        cosine = sum(a * b for a, b in zip(first, current)) / (norm0 * norm)
        maximum = max(
            maximum,
            math.degrees(math.acos(max(-1.0, min(1.0, cosine)))),
        )
    return maximum


def ba_departure(rows: list[dict[str, str]]) -> float:
    fields = ("bax", "bay", "baz")
    initial = tuple(float(rows[0][field]) for field in fields)
    return max(
        math.sqrt(
            sum(
                (float(row[field]) - origin) ** 2
                for field, origin in zip(fields, initial)
            )
        )
        for row in rows
    )


def bag_profile(path: Path) -> dict[str, object]:
    counts: Counter[str] = Counter()
    first: dict[str, int] = {}
    last: dict[str, int] = {}
    timestamp_digest: dict[str, hashlib._Hash] = {}
    with Reader(path) as reader:
        for connection, timestamp, _ in reader.messages():
            topic = connection.topic
            counts[topic] += 1
            first.setdefault(topic, timestamp)
            last[topic] = timestamp
            timestamp_digest.setdefault(topic, hashlib.sha1()).update(
                timestamp.to_bytes(8, "little", signed=False)
            )
    return {
        topic: {
            "messages": counts[topic],
            "first_ns": first[topic],
            "last_ns": last[topic],
            "timestamp_sha1": timestamp_digest[topic].hexdigest(),
        }
        for topic in sorted(counts)
    }


def sleep_events() -> list[dt.datetime]:
    completed = subprocess.run(
        ["pmset", "-g", "log"],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=180,
        check=False,
    )
    events: list[dt.datetime] = []
    for line in completed.stdout.splitlines():
        if "Entering Sleep state" not in line:
            continue
        try:
            local = dt.datetime.strptime(" ".join(line.split()[:2]), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        events.append(local.astimezone())
    return events


def parse_utc(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()


def main() -> int:
    if len(sys.argv) < 3:
        print(f"usage: {sys.argv[0]} <run-root> <repeat> [repeat ...]", file=sys.stderr)
        return 2

    run_root = Path(sys.argv[1]).resolve()
    repeats = tuple(sys.argv[2:])
    expected_bag = ROOT / "data/m2dgr/degraded/hall05_drop5x20.bag"
    source_bag = ROOT / "data/m2dgr/hall_05/lidar_imu.bag"
    if not expected_bag.is_file() or not source_bag.is_file():
        fail("source or degraded Hall05 bag is missing")

    source_profile = bag_profile(source_bag)
    degraded_profile = bag_profile(expected_bag)
    imu_topic = "/handsfree/imu"
    cloud_topic = "/velodyne_points"
    if degraded_profile.get(imu_topic) != source_profile.get(imu_topic):
        fail("dropout bag changed the IMU message count or timestamps")
    if source_profile[cloud_topic]["messages"] != 4017:
        fail("unexpected Hall05 source point-cloud count")
    if degraded_profile[cloud_topic]["messages"] != 3019:
        fail("unexpected Hall05 drop5x20 point-cloud count")
    if degraded_profile[cloud_topic]["first_ns"] != source_profile[cloud_topic]["first_ns"]:
        fail("dropout bag changed the first point-cloud timestamp")
    if degraded_profile[cloud_topic]["last_ns"] != source_profile[cloud_topic]["last_ns"]:
        fail("dropout bag changed the last point-cloud timestamp")

    sleeps = sleep_events()
    records: dict[str, dict[str, object]] = {}
    state_counts: dict[str, int] = {}
    odometry_counts: dict[str, int] = {}
    reference_timestamps: list[str] | None = None

    for repeat in repeats:
        for variant in VARIANTS:
            for level in LEVELS:
                name = f"{variant}_{level}_{repeat}"
                run = run_root / name
                required = (
                    run / "state_log.csv",
                    run / "odometry.csv",
                    run / "run_meta.txt",
                    run / "launch.log",
                )
                if not all(path.is_file() for path in required):
                    fail(f"{name}: missing required output")

                launch_text = (run / "launch.log").read_text(errors="replace")
                for marker in FATAL_MARKERS:
                    if marker in launch_text:
                        fail(f"{name}: fatal marker in launch.log: {marker}")

                states = read_csv(run / "state_log.csv")
                odometry = read_csv(run / "odometry.csv")
                factors_path = run / "gravity_direction.csv"
                factors = read_csv(factors_path) if factors_path.is_file() else []
                if not states or not odometry:
                    fail(f"{name}: empty state or odometry output")
                if {row["variant"] for row in states} != {variant}:
                    fail(f"{name}: state variant label mismatch")

                meta = read_meta(run / "run_meta.txt")
                expected_mode = "ON" if level == "s2" else "OFF"
                expected_sigma = SIGMA_S2 if level == "s2" else 0.0
                if meta.get("variant") != variant:
                    fail(f"{name}: variant metadata mismatch")
                if meta.get("gravity_direction_mode") != expected_mode:
                    fail(f"{name}: direction-mode metadata mismatch")
                if not math.isclose(
                    float(meta.get("gravity_direction_sigma_rad", "nan")),
                    expected_sigma,
                    rel_tol=0.0,
                    abs_tol=1e-15,
                ):
                    fail(f"{name}: direction sigma metadata mismatch")
                if meta.get("bag") != "data/m2dgr/degraded/hall05_drop5x20.bag":
                    fail(f"{name}: unexpected input bag")
                if (meta.get("start_s"), meta.get("duration_s"), meta.get("rate")) != (
                    "0", "400", "0.5"
                ):
                    fail(f"{name}: replay window or rate mismatch")
                if "finished_at" not in meta or meta.get("omp_num_threads") != "1":
                    fail(f"{name}: incomplete or nondeterministic metadata")

                binary = ROOT / "liosam_ws/devel/lib/lio_sam" / meta["imu_node"]
                mapping = ROOT / "liosam_ws/devel/lib/lio_sam/lio_sam_mapOptmization"
                launch = ROOT / meta["launch_file"]
                if sha1(binary) != meta.get("binary_sha1"):
                    fail(f"{name}: IMU binary SHA-1 mismatch")
                if sha1(mapping) != meta.get("mapping_binary_sha1"):
                    fail(f"{name}: mapping binary SHA-1 mismatch")
                if sha1(launch) != meta.get("launch_sha1"):
                    fail(f"{name}: launch SHA-1 mismatch")

                run_sleeps = [
                    event
                    for event in sleeps
                    if parse_utc(meta["started_at"]) <= event <= parse_utc(meta["finished_at"])
                ]
                if run_sleeps:
                    fail(f"{name}: host entered sleep during the run")

                timestamps = [row["timestamp"] for row in states]
                if reference_timestamps is None:
                    reference_timestamps = timestamps
                elif timestamps != reference_timestamps:
                    fail(f"{name}: correction timestamps differ (zero-tolerance gate)")
                state_counts[name] = len(states)
                odometry_counts[name] = len(odometry)

                span = gravity_span(states)
                if variant == "FG-BA" and span > 1e-9:
                    fail(f"{name}: fixed gravity moved by {span:.3e} deg")
                if variant == "GE-BA" and span < 1e-3:
                    fail(f"{name}: online gravity did not move")
                ba_span = ba_departure(states)
                if ba_span < 1e-6:
                    fail(f"{name}: online accelerometer bias did not move")

                factor_summary: dict[str, object] | None = None
                if level == "off":
                    if factors:
                        fail(f"{name}: disabled direction factor was added")
                else:
                    if len(factors) != len(states):
                        fail(f"{name}: factor/state count mismatch")
                    indices = [int(row["factor_index"]) for row in factors]
                    if indices != list(range(1, len(factors) + 1)):
                        fail(f"{name}: factor indices are not contiguous")
                    ages = [float(row["measurement_age_s"]) for row in factors]
                    pre = [float(row["pre_residual_deg"]) for row in factors]
                    post = [float(row["post_residual_deg"]) for row in factors]
                    if not all(math.isfinite(value) for value in ages + pre + post):
                        fail(f"{name}: non-finite factor instrumentation")
                    if min(ages) < -1e-9 or max(ages) > 0.05:
                        fail(f"{name}: direction measurement age out of range")
                    if statistics.median(post) > 1.05 * statistics.median(pre):
                        fail(f"{name}: factor does not reduce its own median residual")
                    factor_summary = {
                        "count": len(factors),
                        "median_pre_deg": statistics.median(pre),
                        "median_post_deg": statistics.median(post),
                        "max_measurement_age_s": max(ages),
                    }

                records[name] = {
                    "state_frames": len(states),
                    "odometry_frames": len(odometry),
                    "gravity_span_deg": span,
                    "ba_departure_mps2": ba_span,
                    "sleep_events": 0,
                    "factor": factor_summary,
                    "binary_sha1": meta["binary_sha1"],
                    "mapping_binary_sha1": meta["mapping_binary_sha1"],
                    "launch_sha1": meta["launch_sha1"],
                }

    if len(set(state_counts.values())) != 1:
        fail(f"state-frame zero-tolerance gate failed: {state_counts}")
    if len(set(odometry_counts.values())) != 1:
        fail(f"odometry-frame zero-tolerance gate failed: {odometry_counts}")

    output = {
        "status": "PASS",
        "validated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "repeats": list(repeats),
        "bag_profiles": {"source": source_profile, "drop5x20": degraded_profile},
        "runs": records,
    }
    report_path = run_root / f"validation_{'_'.join(repeats)}.json"
    report_path.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print("Hall05 drop5x20 LIO-SAM direction-factor validation: PASS")
    print(f"runs={len(records)}, state_frames={next(iter(state_counts.values()))}, "
          f"odometry_frames={next(iter(odometry_counts.values()))}")
    print(f"report={report_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
