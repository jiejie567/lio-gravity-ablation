#!/usr/bin/env python3
"""Structural gate for a paired dynamic-start Online/FixG experiment."""

import argparse
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
from rosbags.highlevel import AnyReader


ROOT = Path(__file__).resolve().parent.parent
G_S2 = 98090.0 / 10000.0


def metadata(run_dir: Path) -> dict[str, str]:
    result = {}
    for line in (run_dir / "run_meta.txt").read_text().splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            result[key.strip()] = value.strip()
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("sequence")
    parser.add_argument("bag")
    parser.add_argument("--start-sec", type=float, required=True)
    parser.add_argument("--duration-sec", type=float, default=60.0)
    args = parser.parse_args()

    sequence = ROOT / "results" / args.sequence
    run_dirs = {name: sequence / name for name in ("A", "RED21")}
    frames = {
        name: pd.read_csv(directory / "state_log.csv").dropna()
        for name, directory in run_dirs.items()
    }
    issues = []

    online, fixed = frames["A"], frames["RED21"]
    if len(online) != len(fixed):
        issues.append(f"frame count differs: A={len(online)}, RED21={len(fixed)}")
    elif not np.array_equal(online["t"].to_numpy(), fixed["t"].to_numpy()):
        issues.append("LiDAR correction timestamps differ")
    if len(online) < 0.9 * args.duration_sec * 10:
        issues.append(f"too few frames for {args.duration_sec:g}s: {len(online)}")

    bag = ROOT / args.bag
    with AnyReader([bag]) as reader:
        expected_start = reader.start_time / 1e9 + args.start_sec
    for name, frame in frames.items():
        delay = float(frame["t"].iloc[0] - expected_start)
        span = float(frame["t"].iloc[-1] - frame["t"].iloc[0])
        if not 0.2 <= delay <= 1.5:
            issues.append(f"{name} first-state delay {delay:.3f}s is inconsistent with start")
        if not args.duration_sec - 2.0 <= span <= args.duration_sec:
            issues.append(f"{name} state span {span:.3f}s is inconsistent with duration")

        gravity = frame[["gx", "gy", "gz"]].to_numpy()
        norms = np.linalg.norm(gravity, axis=1)
        if np.max(np.abs(norms - G_S2)) > 1e-3:
            issues.append(f"{name} gravity norm differs from {G_S2:.4f}")
        for state in ("ba", "bg"):
            cols = [f"{state}{axis}" for axis in "xyz"]
            if np.max(np.abs(frame[cols].to_numpy() - frame[cols].iloc[0].to_numpy())) < 1e-12:
                issues.append(f"{name} {state} did not remain online")

    fixed_gravity = fixed[["gx", "gy", "gz"]].to_numpy()
    if np.max(np.abs(fixed_gravity - fixed_gravity[0])) > 1e-12:
        issues.append("RED21 gravity is not constant")
    online_gravity = online[["gx", "gy", "gz"]].to_numpy()
    if np.max(np.abs(online_gravity - online_gravity[0])) < 1e-12:
        issues.append("A gravity did not remain online")

    ga = online_gravity[0] / np.linalg.norm(online_gravity[0])
    gf = fixed_gravity[0] / np.linalg.norm(fixed_gravity[0])
    init_angle = float(np.degrees(np.arccos(np.clip(ga @ gf, -1.0, 1.0))))
    if init_angle > 0.1:
        issues.append(f"initial gravity differs by {init_angle:.3f} deg")

    binaries = {
        "A": ROOT / "catkin_ws/devel/lib/fast_lio/fastlio_mapping",
        "RED21": ROOT / "catkin_ws/devel/lib/fast_lio/fastlio_mapping_redg",
    }
    for name, directory in run_dirs.items():
        meta = metadata(directory)
        expected_sha = hashlib.sha1(binaries[name].read_bytes()).hexdigest()[:12]
        if meta.get("fastlio_binary_sha1") != expected_sha:
            issues.append(f"{name} binary fingerprint mismatch")
        if float(meta.get("play_start_sec", "nan")) != args.start_sec:
            issues.append(f"{name} start offset metadata mismatch")
        if float(meta.get("play_duration_sec", "nan")) != args.duration_sec:
            issues.append(f"{name} duration metadata mismatch")
        console = (directory / "console.log").read_text(errors="replace")
        if "IMU Initial Done" not in console or "[FATAL]" in console:
            issues.append(f"{name} console failed initialization audit")

    if issues:
        for issue in issues:
            print(f"FAIL: {issue}")
        return 1
    print(
        f"PASS {args.sequence}: {len(online)} paired frames, "
        f"span={online.t.iloc[-1] - online.t.iloc[0]:.3f}s, "
        f"initial-g delta={init_angle:.6f} deg"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
