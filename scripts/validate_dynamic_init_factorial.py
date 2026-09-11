#!/usr/bin/env python3
"""Structural and data gates for one four-manifold dynamic-start phase."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from rosbags.highlevel import AnyReader


ROOT = Path(__file__).resolve().parent.parent
G_S2 = 98090.0 / 10000.0
VARIANTS = {
    "A": {
        "gravity_constant": False,
        "ba_constant": False,
        "binary": "fastlio_mapping",
        "launch": "mapping_exp",
    },
    "RED21": {
        "gravity_constant": True,
        "ba_constant": False,
        "binary": "fastlio_mapping_redg",
        "launch": "mapping_exp_redg",
    },
    "RED20": {
        "gravity_constant": False,
        "ba_constant": True,
        "binary": "fastlio_mapping_redb",
        "launch": "mapping_exp_redb",
    },
    "RED18": {
        "gravity_constant": True,
        "ba_constant": True,
        "binary": "fastlio_mapping_red",
        "launch": "mapping_exp_red",
    },
}


def metadata(run_dir: Path) -> dict[str, str]:
    out = {}
    for line in (run_dir / "run_meta.txt").read_text().splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            out[key.strip()] = value.strip()
    return out


def gt_path_length(path: Path, lower: float, upper: float) -> float:
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            values = [float(value) for value in line.replace(",", " ").split()]
        except ValueError:
            continue
        if len(values) >= 9:
            rows.append(values[1:5])
        elif len(values) >= 8:
            rows.append(values[:4])
    samples = np.asarray(rows)
    samples = samples[np.argsort(samples[:, 0])]
    inner = samples[(samples[:, 0] > lower) & (samples[:, 0] < upper)]
    boundary = []
    for timestamp in (lower, upper):
        boundary.append([
            timestamp,
            *(np.interp(timestamp, samples[:, 0], samples[:, axis])
              for axis in range(1, 4)),
        ])
    clipped = np.vstack((boundary[0], inner, boundary[1]))
    return float(np.linalg.norm(np.diff(clipped[:, 1:4], axis=0), axis=1).sum())


def state_motion(frame: pd.DataFrame, prefix: str) -> float:
    columns = [f"{prefix}{axis}" for axis in "xyz"]
    values = frame[columns].to_numpy()
    return float(np.max(np.abs(values - values[0])))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("sequence")
    parser.add_argument("bag")
    parser.add_argument("--gt", required=True)
    parser.add_argument("--start-sec", type=float, required=True)
    parser.add_argument("--duration-sec", type=float, default=60.0)
    args = parser.parse_args()

    sequence_dir = ROOT / "results" / args.sequence
    run_dirs = {name: sequence_dir / name for name in VARIANTS}
    issues = []
    estimator_failures = []
    frames = {}
    metas = {}
    for name, run_dir in run_dirs.items():
        missing = []
        for required in ("state_log.csv", "run_meta.txt", "console.log"):
            if not (run_dir / required).exists():
                missing.append(required)
                issues.append(f"{name} missing {required}")
        if missing:
            continue
        frames[name] = pd.read_csv(run_dir / "state_log.csv").dropna()
        metas[name] = metadata(run_dir)
    if len(frames) != len(VARIANTS):
        for issue in issues:
            print(f"FAIL: {issue}")
        return 1

    bag = ROOT / args.bag
    with AnyReader([bag]) as reader:
        expected_start = reader.start_time / 1e9 + args.start_sec

    baseline = frames["A"]
    baseline_time = baseline["t"].to_numpy()
    baseline_g = baseline[["gx", "gy", "gz"]].to_numpy()
    baseline_g0 = baseline_g[0] / np.linalg.norm(baseline_g[0])
    gt_length = gt_path_length(
        ROOT / args.gt, float(baseline_time[0]), float(baseline_time[-1]))

    binary_root = ROOT / "catkin_ws" / "devel" / "lib" / "fast_lio"
    run_summary = {}
    for name, properties in VARIANTS.items():
        frame = frames[name]
        times = frame["t"].to_numpy()
        numeric = frame.select_dtypes(include=[np.number]).to_numpy()
        if not np.isfinite(numeric).all():
            issues.append(f"{name} contains non-finite state values")
        if len(frame) != len(baseline):
            issues.append(f"{name} frames {len(frame)} != A {len(baseline)}")
        elif not np.array_equal(times, baseline_time):
            issues.append(f"{name} LiDAR correction timestamps differ from A")

        delay = float(times[0] - expected_start)
        span = float(times[-1] - times[0])
        if not 0.2 <= delay <= 1.5:
            issues.append(f"{name} first-state delay {delay:.3f}s")
        if not args.duration_sec - 2.0 <= span <= args.duration_sec:
            issues.append(f"{name} state span {span:.3f}s")

        gravity = frame[["gx", "gy", "gz"]].to_numpy()
        gravity_norm_error = float(np.max(
            np.abs(np.linalg.norm(gravity, axis=1) - G_S2)))
        if gravity_norm_error > 1e-3:
            issues.append(f"{name} gravity norm differs from {G_S2:.4f}")
        gravity_motion = state_motion(frame, "g")
        if properties["gravity_constant"] and gravity_motion > 1e-12:
            issues.append(f"{name} gravity should be constant ({gravity_motion:.2e})")
        if not properties["gravity_constant"] and gravity_motion < 1e-12:
            issues.append(f"{name} gravity should remain online")

        ba_motion = state_motion(frame, "ba")
        if properties["ba_constant"] and ba_motion > 1e-12:
            issues.append(f"{name} ba should be constant ({ba_motion:.2e})")
        if not properties["ba_constant"] and ba_motion < 1e-12:
            issues.append(f"{name} ba should remain online")
        if state_motion(frame, "bg") < 1e-12:
            issues.append(f"{name} bg should remain online")

        initial_g = gravity[0] / np.linalg.norm(gravity[0])
        initial_angle = float(np.degrees(np.arccos(
            np.clip(initial_g @ baseline_g0, -1.0, 1.0))))
        if initial_angle > 0.1:
            issues.append(f"{name} initial gravity differs by {initial_angle:.3f} deg")
        # The first state log is written after the first LiDAR correction, not
        # at the common initializer boundary. Online-ba manifolds can therefore
        # have taken their first update while removed-ba manifolds still report
        # the shared zero initializer. Check that every run starts near that
        # configured zero rather than requiring post-update bit equality.
        initial_ba_norm = float(np.linalg.norm(
            frame[["bax", "bay", "baz"]].iloc[0].to_numpy()))
        if initial_ba_norm > 1e-3:
            issues.append(f"{name} first logged ba norm is {initial_ba_norm:.2e}")

        position = frame[["px", "py", "pz"]].to_numpy()
        estimate_length = float(np.linalg.norm(
            np.diff(position, axis=0), axis=1).sum())
        arc_ratio = estimate_length / gt_length
        if not 0.6 <= arc_ratio <= 1.6:
            # The shared GT has already passed the full-sequence gate. If a
            # complete, finite, timestamp-matched candidate leaves the arc
            # band while the comparison remains valid, this is an estimator
            # failure—not permission to discard and rerun an adverse result.
            # Return a distinct status so callers can retain it as a planned
            # failure outcome without admitting it to ordinary accuracy sums.
            estimator_failures.append(
                f"{name} arc ratio {arc_ratio:.3f} outside [0.6,1.6]")

        expected_binary = binary_root / properties["binary"]
        expected_sha = hashlib.sha1(expected_binary.read_bytes()).hexdigest()[:12]
        meta = metas[name]
        if meta.get("fastlio_binary_sha1") != expected_sha:
            issues.append(f"{name} binary fingerprint mismatch")
        if meta.get("launch") != properties["launch"]:
            issues.append(f"{name} launch mismatch")
        if abs(float(meta.get("play_start_sec", "nan")) - args.start_sec) > 1e-9:
            issues.append(f"{name} start offset metadata mismatch")
        if abs(float(meta.get("play_duration_sec", "nan")) - args.duration_sec) > 1e-9:
            issues.append(f"{name} duration metadata mismatch")
        if not meta.get("method", "").startswith("A (freeze_gravity=false freeze_ba=false"):
            issues.append(f"{name} reduced launch was combined with a freeze proxy")
        console = (run_dirs[name] / "console.log").read_text(errors="replace")
        if "IMU Initial Done" not in console or "[FATAL]" in console:
            issues.append(f"{name} console failed initialization audit")

        run_summary[name] = {
            "frames": int(len(frame)),
            "span_s": span,
            "gravity_motion": gravity_motion,
            "ba_motion": ba_motion,
            "arc_ratio": arc_ratio,
            "binary_sha1": expected_sha,
        }

    metrics_path = sequence_dir / "analysis" / "metrics.json"
    if not metrics_path.exists():
        issues.append("analysis/metrics.json missing")
    else:
        metrics = json.loads(metrics_path.read_text()).get("runs", {})
        if set(VARIANTS) - set(metrics):
            issues.append("analysis metrics do not contain all four variants")
        elif max(metrics["A"].get("rmse_roll_deg", 99.0),
                 metrics["A"].get("rmse_pitch_deg", 99.0)) >= 20.0:
            issues.append("baseline attitude GT gate failed")

    if issues:
        for issue in issues:
            print(f"FAIL: {issue}")
        return 1

    status = "PASS" if not estimator_failures else "COMPLETE_ESTIMATOR_FAILURE"
    print(
        f"{status} {args.sequence}: {len(baseline)} frames, GT={gt_length:.2f}m, "
        "four true manifolds and structural gates verified"
    )
    for name, values in run_summary.items():
        print(
            f"  {name:5s} arc={values['arc_ratio']:.3f} "
            f"g_motion={values['gravity_motion']:.3e} "
            f"ba_motion={values['ba_motion']:.3e} sha={values['binary_sha1']}"
        )
    for failure in estimator_failures:
        print(
            "  OUTCOME: " + failure
            + "; excluded from ordinary accuracy admission and retained as failure"
        )
    return 2 if estimator_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
