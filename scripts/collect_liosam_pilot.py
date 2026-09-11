#!/usr/bin/env python3
"""Compute diagnostic metrics for the deterministic LIO-SAM pilot only.

This deliberately writes a separate file, not report/summary.json. A single
60 s segment is not admissible as a paper result.
"""

from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path

import numpy as np


VARIANTS = ("FG-BA", "FG-B0", "GE-BA", "GE-B0")
POSITION_FIELDS = (
    "field.pose.pose.position.x",
    "field.pose.pose.position.y",
    "field.pose.pose.position.z",
)


def load_odometry(path: Path) -> tuple[np.ndarray, np.ndarray]:
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    time = np.array([float(row["%time"]) * 1e-9 for row in rows])
    position = np.array(
        [[float(row[field]) for field in POSITION_FIELDS] for row in rows]
    )
    return time, position


def load_gt(path: Path) -> tuple[np.ndarray, np.ndarray]:
    values = np.loadtxt(path)
    return values[:, 0], values[:, 1:4]


def rigid_alignment(source: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    source_mean = source.mean(axis=0)
    target_mean = target.mean(axis=0)
    covariance = (target - target_mean).T @ (source - source_mean)
    left, _, right_t = np.linalg.svd(covariance)
    correction = np.diag([1.0, 1.0, np.sign(np.linalg.det(left @ right_t))])
    rotation = left @ correction @ right_t
    translation = target_mean - rotation @ source_mean
    return rotation, translation


def main() -> int:
    if len(sys.argv) != 4:
        print(f"usage: {sys.argv[0]} <run-root> <gt.txt> <output.json>", file=sys.stderr)
        return 2

    root, gt_path, output_path = map(Path, sys.argv[1:])
    gt_time, gt_position = load_gt(gt_path)
    result: dict[str, object] = {
        "status": "pilot_only_not_paper_evidence",
        "sequence": "M2DGR Hall05 first 60 s",
        "playback_rate": 0.5,
        "alignment": "rigid SE(3), first 10 s",
        "runs": {},
    }

    for variant in VARIANTS:
        time, estimate = load_odometry(root / variant / "odometry.csv")
        valid = (time >= gt_time[0]) & (time <= gt_time[-1])
        time = time[valid]
        estimate = estimate[valid]
        truth = np.column_stack(
            [np.interp(time, gt_time, gt_position[:, axis]) for axis in range(3)]
        )
        align_count = max(10, int(np.searchsorted(time, time[0] + 10.0)))
        rotation, translation = rigid_alignment(
            estimate[:align_count], truth[:align_count]
        )
        aligned = estimate @ rotation.T + translation
        error = aligned - truth
        error_norm = np.linalg.norm(error, axis=1)
        arc_length = float(np.linalg.norm(np.diff(truth, axis=0), axis=1).sum())
        result["runs"][variant] = {
            "frames": int(len(time)),
            "duration_s": float(time[-1] - time[0]),
            "gt_arc_length_m": arc_length,
            "rmse_z_m": float(np.sqrt(np.mean(error[:, 2] ** 2))),
            "ate_rmse_m": float(np.sqrt(np.mean(error_norm ** 2))),
            "final_position_error_m": float(error_norm[-1]),
        }

    baseline = result["runs"]["FG-BA"]
    for variant in VARIANTS:
        run = result["runs"][variant]
        run["delta_rmse_z_pct_vs_fg_ba"] = (
            run["rmse_z_m"] / baseline["rmse_z_m"] - 1.0
        ) * 100.0
        run["delta_ate_pct_vs_fg_ba"] = (
            run["ate_rmse_m"] / baseline["ate_rmse_m"] - 1.0
        ) * 100.0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
