#!/usr/bin/env python3
"""Compute non-paper diagnostic metrics for a short MCD LIO-SAM ablation.

The LIO-SAM odometry pose is the Ouster sensor pose.  Before alignment, this
script composes the dataset's released T_lidar_body transform so the evaluated
position is the VectorNav/body position used by MCD ground truth.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation


VARIANTS = ("FG-BA", "FG-B0", "GE-BA", "GE-B0")
POS = tuple(f"field.pose.pose.position.{axis}" for axis in "xyz")
QUAT = tuple(f"field.pose.pose.orientation.{axis}" for axis in "xyzw")

T_LIDAR_BODY = {
    "atv": np.array([-0.060649229060416594, -0.012837544242408117,
                     -0.020492606896077407]),
    "handheld": np.array([-0.04894521120494695, -0.03126929060348084,
                          -0.01755515794222565]),
}


def load_estimate(path: Path, setup: str) -> tuple[np.ndarray, np.ndarray]:
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    time = np.array([float(row["%time"]) * 1e-9 for row in rows])
    lidar_position = np.array([[float(row[field]) for field in POS] for row in rows])
    quaternion = np.array([[float(row[field]) for field in QUAT] for row in rows])
    body_offset_world = Rotation.from_quat(quaternion).apply(T_LIDAR_BODY[setup])
    return time, lidar_position + body_offset_world


def load_gt(path: Path) -> tuple[np.ndarray, np.ndarray]:
    values = np.genfromtxt(path, delimiter=",", names=True)
    return values["t"], np.column_stack((values["x"], values["y"], values["z"]))


def align(source: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    source_mean = source.mean(axis=0)
    target_mean = target.mean(axis=0)
    covariance = (target - target_mean).T @ (source - source_mean)
    left, _, right_t = np.linalg.svd(covariance)
    correction = np.diag([1.0, 1.0, np.sign(np.linalg.det(left @ right_t))])
    rotation = left @ correction @ right_t
    translation = target_mean - rotation @ source_mean
    return rotation, translation


def main() -> int:
    if len(sys.argv) != 5 or sys.argv[2] not in T_LIDAR_BODY:
        print(f"usage: {sys.argv[0]} <run-root> <atv|handheld> <gt.csv> <output.json>",
              file=sys.stderr)
        return 2
    root = Path(sys.argv[1])
    setup = sys.argv[2]
    gt_path = Path(sys.argv[3])
    output = Path(sys.argv[4])
    gt_time, gt_position = load_gt(gt_path)
    result: dict[str, object] = {
        "status": "pilot_only_not_paper_evidence",
        "sequence": "MCD ntu_day_10 first 30 s" if setup == "atv" else "MCD handheld first 30 s",
        "playback_rate": 0.5,
        "alignment": "rigid SE(3), first 10 s, evaluated in VectorNav/body frame",
        "runs": {},
    }
    for variant in VARIANTS:
        time, estimate = load_estimate(root / variant / "odometry.csv", setup)
        valid = (time >= gt_time[0]) & (time <= gt_time[-1])
        time, estimate = time[valid], estimate[valid]
        truth = np.column_stack([
            np.interp(time, gt_time, gt_position[:, axis]) for axis in range(3)
        ])
        align_count = max(10, int(np.searchsorted(time, time[0] + 10.0)))
        rotation, translation = align(estimate[:align_count], truth[:align_count])
        aligned = estimate @ rotation.T + translation
        error = aligned - truth
        norm = np.linalg.norm(error, axis=1)
        result["runs"][variant] = {
            "frames": int(len(time)),
            "duration_s": float(time[-1] - time[0]),
            "gt_arc_length_m": float(np.linalg.norm(np.diff(truth, axis=0), axis=1).sum()),
            "rmse_z_m": float(np.sqrt(np.mean(error[:, 2] ** 2))),
            "ate_rmse_m": float(np.sqrt(np.mean(norm ** 2))),
            "final_position_error_m": float(norm[-1]),
        }
    baseline = result["runs"]["FG-BA"]
    for run in result["runs"].values():
        run["delta_rmse_z_pct_vs_fg_ba"] = (run["rmse_z_m"] / baseline["rmse_z_m"] - 1) * 100
        run["delta_ate_pct_vs_fg_ba"] = (run["ate_rmse_m"] / baseline["ate_rmse_m"] - 1) * 100
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
