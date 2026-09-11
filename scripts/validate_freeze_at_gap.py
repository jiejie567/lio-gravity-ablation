#!/usr/bin/env python3
"""Validate the matched Online -> Freeze@Gap mechanism pair."""
import argparse
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
G_S2 = 98090.0 / 10000.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("sequence")
    parser.add_argument("--online", default="A_gapbranch")
    parser.add_argument("--freeze", default="FreezeAtGap")
    parser.add_argument("--gap-s", type=float, required=True)
    args = parser.parse_args()

    sequence = ROOT / "results" / args.sequence
    online_dir = sequence / args.online
    freeze_dir = sequence / args.freeze
    online = pd.read_csv(online_dir / "state_log.csv").dropna()
    frozen = pd.read_csv(freeze_dir / "state_log.csv").dropna()
    event = pd.read_csv(freeze_dir / "freeze_event.csv").dropna()
    issues = []

    if len(event) != 1:
        issues.append(f"freeze event rows={len(event)}, expected 1")
    if len(online) != len(frozen):
        issues.append(f"frame count {len(online)} vs {len(frozen)}")
    if len(online) == len(frozen) and not np.array_equal(
            online["t"].to_numpy(), frozen["t"].to_numpy()):
        issues.append("LiDAR correction timestamps differ")

    if len(event) == 1:
        record = event.iloc[0]
        activation = float(record["activation_lidar_time"])
        snapshot = float(record["snapshot_lidar_time"])
        trigger = int(np.searchsorted(frozen["t"].to_numpy(), activation))
        if trigger <= 0 or trigger >= len(frozen):
            issues.append(f"invalid trigger index {trigger}")
        else:
            prefix_online = online.iloc[:trigger].to_numpy()
            prefix_frozen = frozen.iloc[:trigger].to_numpy()
            if not np.array_equal(prefix_online, prefix_frozen):
                maximum = float(np.max(np.abs(prefix_online - prefix_frozen)))
                issues.append(f"pre-trigger state/map prefix differs (max {maximum:.3e})")
            if abs(float(frozen["t"].iloc[trigger - 1]) - snapshot) > 2e-6:
                issues.append("snapshot is not the last completed LiDAR correction")
            gap = activation - snapshot
            if not 0.8 * args.gap_s <= gap <= 1.2 * args.gap_s:
                issues.append(f"observed correction gap {gap:.3f}s != {args.gap_s:.3f}s")

            gravity = frozen[["gx", "gy", "gz"]].to_numpy()
            reference = record[["gx", "gy", "gz"]].to_numpy(dtype=float)
            if np.max(np.abs(gravity[trigger - 1:] - reference)) > 1e-9:
                issues.append("Freeze@Gap gravity is not constant after the snapshot")
            online_gravity = online[["gx", "gy", "gz"]].to_numpy()
            if np.max(np.abs(online_gravity[trigger:] - reference)) < 1e-9:
                issues.append("Online control gravity did not remain online")

    for label, frame in ((args.online, online), (args.freeze, frozen)):
        norms = np.linalg.norm(frame[["gx", "gy", "gz"]].to_numpy(), axis=1)
        if np.max(np.abs(norms - G_S2)) > 1e-3:
            issues.append(f"{label} gravity norm is not {G_S2:.4f}")

    binary = ROOT / "catkin_ws" / "devel" / "lib" / "fast_lio" / "fastlio_mapping"
    expected_sha = hashlib.sha1(binary.read_bytes()).hexdigest()[:12]
    for label, directory in ((args.online, online_dir), (args.freeze, freeze_dir)):
        meta = {}
        for line in (directory / "run_meta.txt").read_text().splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                meta[key.strip()] = value.strip()
        if meta.get("fastlio_binary_sha1") != expected_sha:
            issues.append(
                f"{label} binary {meta.get('fastlio_binary_sha1')} != {expected_sha}")
        console = (directory / "console.log").read_text(errors="replace")
        if "delayed-frozen gravity drifted" in console or "[FATAL]" in console:
            issues.append(f"{label} console contains a freeze-structure failure")

    if issues:
        for issue in issues:
            print(f"FAIL: {issue}")
        return 1
    record = event.iloc[0]
    print(
        f"PASS {args.sequence}: {len(frozen)} frames, bit-identical prefix, "
        f"snapshot={record['snapshot_elapsed_s']:.3f}s, "
        f"activation={record['activation_elapsed_s']:.3f}s, "
        f"binary={expected_sha}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
