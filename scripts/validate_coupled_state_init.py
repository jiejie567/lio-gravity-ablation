#!/usr/bin/env python3
"""Structural gate for the paired gravity--accelerometer-bias intervention."""

import argparse
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial.transform import Rotation


ROOT = Path(__file__).resolve().parent.parent
G_S2 = 98090.0 / 10000.0
FULL_RUNS = ("base", "g_p2", "gb_p2", "g_m2", "gb_m2")
PARTIAL_RUNS = FULL_RUNS[:3]


def metadata(run_dir: Path) -> dict[str, str]:
    values = {}
    for line in (run_dir / "run_meta.txt").read_text().splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            values[key.strip()] = value.strip()
    return values


def angle_deg(first: np.ndarray, second: np.ndarray) -> float:
    first = first / np.linalg.norm(first)
    second = second / np.linalg.norm(second)
    return float(np.degrees(np.arccos(np.clip(first @ second, -1.0, 1.0))))


def effective(frame: pd.DataFrame) -> np.ndarray:
    gravity = frame[["gx", "gy", "gz"]].to_numpy(dtype=float)
    ba = frame[["bax", "bay", "baz"]].to_numpy(dtype=float)
    rotation = Rotation.from_quat(
        frame[["qx", "qy", "qz", "qw"]].to_numpy(dtype=float)
    )
    return gravity - rotation.apply(ba)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("sequence")
    parser.add_argument("--partial", action="store_true")
    parser.add_argument("--duration-sec", type=float, default=60.0)
    parser.add_argument("--angle-deg", type=float, default=2.0)
    args = parser.parse_args()

    names = PARTIAL_RUNS if args.partial else FULL_RUNS
    sequence_dir = ROOT / "results" / args.sequence
    issues: list[str] = []
    frames: dict[str, pd.DataFrame] = {}
    metas: dict[str, dict[str, str]] = {}

    for name in names:
        run_dir = sequence_dir / name
        for required in ("state_log.csv", "run_meta.txt", "console.log", "exp_params.yaml"):
            if not (run_dir / required).exists():
                issues.append(f"{name} missing {required}")
        if issues and not (run_dir / "state_log.csv").exists():
            continue
        frames[name] = pd.read_csv(run_dir / "state_log.csv").dropna()
        metas[name] = metadata(run_dir)

    if len(frames) != len(names):
        for issue in issues:
            print(f"FAIL: {issue}")
        return 1

    base = frames["base"]
    reference_times = base["t"].to_numpy(dtype=float)
    expected_binary = ROOT / "catkin_ws/devel/lib/fast_lio/fastlio_mapping"
    expected_sha = hashlib.sha1(expected_binary.read_bytes()).hexdigest()[:12]

    for name, frame in frames.items():
        numeric = frame.select_dtypes(include=[np.number]).to_numpy()
        if not np.isfinite(numeric).all():
            issues.append(f"{name} contains non-finite state values")
        if len(frame) != len(base):
            issues.append(f"{name} frames {len(frame)} != base {len(base)}")
        elif not np.array_equal(frame["t"].to_numpy(dtype=float), reference_times):
            issues.append(f"{name} LiDAR timestamps differ from base")
        span = float(frame["t"].iloc[-1] - frame["t"].iloc[0])
        if not args.duration_sec - 2.0 <= span <= args.duration_sec:
            issues.append(f"{name} span {span:.3f}s is inconsistent with duration")

        gravity = frame[["gx", "gy", "gz"]].to_numpy(dtype=float)
        if np.max(np.abs(np.linalg.norm(gravity, axis=1) - G_S2)) > 1e-3:
            issues.append(f"{name} gravity norm differs from {G_S2:.4f}")
        if np.max(np.abs(gravity - gravity[0])) < 1e-12:
            issues.append(f"{name} gravity did not remain online")
        bias = frame[["bax", "bay", "baz"]].to_numpy(dtype=float)
        if np.max(np.abs(bias - bias[0])) < 1e-12:
            issues.append(f"{name} ba did not remain online")

        meta = metas[name]
        if meta.get("fastlio_binary_sha1") != expected_sha:
            issues.append(f"{name} binary fingerprint mismatch")
        if meta.get("launch") != "mapping_exp":
            issues.append(f"{name} did not use mapping_exp")
        if not meta.get("method", "").startswith(
            "A (freeze_gravity=false freeze_ba=false"
        ):
            issues.append(f"{name} is not Online g + Online ba")
        if abs(float(meta.get("play_duration_sec", "nan")) - args.duration_sec) > 1e-9:
            issues.append(f"{name} duration metadata mismatch")
        console = (sequence_dir / name / "console.log").read_text(errors="replace")
        if "IMU Initial Done" not in console or "[FATAL]" in console:
            issues.append(f"{name} console failed initialization audit")

    base_g = base[["gx", "gy", "gz"]].iloc[0].to_numpy(dtype=float)
    base_h = effective(base)[0]
    intervention_report = {}
    for sign, g_name, pair_name in (("plus", "g_p2", "gb_p2"),
                                    ("minus", "g_m2", "gb_m2")):
        if pair_name not in frames:
            continue
        g_frame, pair = frames[g_name], frames[pair_name]
        g0 = g_frame[["gx", "gy", "gz"]].iloc[0].to_numpy(dtype=float)
        pair_g0 = pair[["gx", "gy", "gz"]].iloc[0].to_numpy(dtype=float)
        g_angle = angle_deg(base_g, g0)
        pair_angle = angle_deg(base_g, pair_g0)
        same_tilt = angle_deg(g0, pair_g0)
        if abs(g_angle - args.angle_deg) > 0.1:
            issues.append(f"{g_name} initial tilt is {g_angle:.3f} deg")
        if abs(pair_angle - args.angle_deg) > 0.1:
            issues.append(f"{pair_name} initial tilt is {pair_angle:.3f} deg")
        if same_tilt > 0.05:
            issues.append(f"{g_name}/{pair_name} gravity differs by {same_tilt:.3f} deg")

        g_h_delta = float(np.linalg.norm(effective(g_frame)[0] - base_h))
        pair_h_delta = float(np.linalg.norm(effective(pair)[0] - base_h))
        ratio = pair_h_delta / g_h_delta if g_h_delta > 0 else float("inf")
        if g_h_delta < 0.2:
            issues.append(f"{g_name} effective intervention is only {g_h_delta:.4f} m/s^2")
        if ratio > 0.05:
            issues.append(
                f"{pair_name} compensation ratio {ratio:.4f} exceeds 0.05"
            )
        intervention_report[sign] = {
            "gravity_only_h_delta": g_h_delta,
            "paired_h_delta": pair_h_delta,
            "compensation_ratio": ratio,
        }

    if issues:
        for issue in issues:
            print(f"FAIL: {issue}")
        return 1

    mode = "pilot" if args.partial else "full"
    print(
        f"PASS {args.sequence} ({mode}): {len(base)} frames, "
        f"span={base.t.iloc[-1] - base.t.iloc[0]:.3f}s, sha={expected_sha}"
    )
    for sign, values in intervention_report.items():
        print(
            f"  {sign}: gravity-only |dh0|={values['gravity_only_h_delta']:.6f}, "
            f"paired |dh0|={values['paired_h_delta']:.6f}, "
            f"ratio={values['compensation_ratio']:.6f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
