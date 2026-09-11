#!/usr/bin/env python3
"""Validate a matched Online -> covariance-consistent warm FixG21 pair."""
import argparse
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
G_S2 = 98090.0 / 10000.0


def read_meta(path: Path) -> dict[str, str]:
    result = {}
    for line in path.read_text().splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            result[key.strip()] = value.strip()
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("sequence")
    parser.add_argument("--online", default="A_warm21")
    parser.add_argument("--warm", required=True)
    gap_group = parser.add_mutually_exclusive_group(required=True)
    gap_group.add_argument("--gap-s", type=float)
    gap_group.add_argument("--max-gap-s", type=float)
    parser.add_argument("--trigger-s", type=float, required=True)
    parser.add_argument("--projection", choices=("marginal", "conditional"), required=True)
    args = parser.parse_args()

    sequence = ROOT / "results" / args.sequence
    online_dir = sequence / args.online
    warm_dir = sequence / args.warm
    online = pd.read_csv(online_dir / "state_log.csv").dropna()
    warm = pd.read_csv(warm_dir / "state_log.csv").dropna()
    event = pd.read_csv(warm_dir / "warm_fixg_event.csv").dropna()
    issues: list[str] = []

    if len(event) != 1:
        issues.append(f"event rows={len(event)}, expected 1")
    if len(online) != len(warm):
        issues.append(f"frame count {len(online)} vs {len(warm)}")
    if len(online) == len(warm) and not np.array_equal(online.t.to_numpy(), warm.t.to_numpy()):
        issues.append("LiDAR correction timestamps differ")

    if len(event) == 1 and len(online) == len(warm):
        row = event.iloc[0]
        activation = float(row.activation_lidar_time)
        snapshot = float(row.snapshot_lidar_time)
        if abs(float(row.requested_elapsed_s) - args.trigger_s) > 1e-9:
            issues.append(
                f"requested trigger {float(row.requested_elapsed_s):.3f}s "
                f"!= {args.trigger_s:.3f}s"
            )
        trigger = int(np.searchsorted(warm.t.to_numpy(), activation))
        if trigger <= 0 or trigger >= len(warm):
            issues.append(f"invalid trigger row {trigger}")
        else:
            if not np.array_equal(online.iloc[:trigger].to_numpy(), warm.iloc[:trigger].to_numpy()):
                delta = np.max(np.abs(online.iloc[:trigger].to_numpy() - warm.iloc[:trigger].to_numpy()))
                issues.append(f"pre-switch state prefix differs (max {delta:.3e})")
            if abs(float(warm.t.iloc[trigger - 1]) - snapshot) > 2e-6:
                issues.append("snapshot is not the preceding completed correction")
            gap = activation - snapshot
            if args.max_gap_s is not None:
                if not 0.0 < gap <= args.max_gap_s:
                    issues.append(
                        f"observed correction gap {gap:.3f}s exceeds "
                        f"{args.max_gap_s:.3f}s"
                    )
            elif not 0.8 * args.gap_s <= gap <= 1.2 * args.gap_s:
                issues.append(f"observed correction gap {gap:.3f}s != {args.gap_s:.3f}s")
            if not np.all(warm.active_dof.iloc[:trigger].to_numpy() == 23):
                issues.append("warm branch was reduced before the switch")
            if not np.all(warm.active_dof.iloc[trigger:].to_numpy() == 21):
                issues.append("warm branch is not 21D after the switch")
            if not np.all(online.active_dof.to_numpy() == 23):
                issues.append("Online control did not remain 23D")

            reference = row[["gx", "gy", "gz"]].to_numpy(dtype=float)
            gravity = warm[["gx", "gy", "gz"]].to_numpy()
            if np.max(np.abs(gravity[trigger - 1:] - reference)) > 1e-9:
                issues.append("Warm FixG21 gravity is not constant after the snapshot")

        if str(row.projection) != args.projection:
            issues.append(f"projection={row.projection}, expected {args.projection}")
        pgg = np.array([[row.pgg00, row.pgg01], [row.pgg01, row.pgg11]], dtype=float)
        if np.linalg.eigvalsh(pgg).min() <= 0.0:
            issues.append("pre-switch gravity covariance is not positive definite")
        if float(row.projected_min_eig) <= 0.0:
            issues.append("projected active covariance is not positive definite")

    for label, frame in ((args.online, online), (args.warm, warm)):
        norms = np.linalg.norm(frame[["gx", "gy", "gz"]].to_numpy(), axis=1)
        if np.max(np.abs(norms - G_S2)) > 1e-3:
            issues.append(f"{label} gravity norm is not {G_S2:.4f}")

    binary = ROOT / "catkin_ws/devel/lib/fast_lio/fastlio_mapping"
    expected_sha = hashlib.sha1(binary.read_bytes()).hexdigest()[:12]
    for label, directory in ((args.online, online_dir), (args.warm, warm_dir)):
        meta = read_meta(directory / "run_meta.txt")
        if meta.get("fastlio_binary_sha1") != expected_sha:
            issues.append(f"{label} binary {meta.get('fastlio_binary_sha1')} != {expected_sha}")
        console = (directory / "console.log").read_text(errors="replace")
        if "[FATAL]" in console or "Warm FixG21 structure drifted" in console:
            issues.append(f"{label} console contains a structural failure")

    if issues:
        for issue in issues:
            print(f"FAIL: {issue}")
        return 1
    print(
        f"PASS {args.sequence}/{args.warm}: {len(warm)} frames, bit-identical prefix, "
        f"23D->21D {args.projection}, binary={expected_sha}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
