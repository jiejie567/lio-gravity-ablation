#!/usr/bin/env python3
"""Collect the structurally valid 60 s gravity-direction pilot."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

from collect_liosam_pilot import load_gt, load_odometry, rigid_alignment


RUNS = ("FG-BA_D0", "FG-BA_D1", "GE-BA_D0", "GE-BA_D1")


def contrast(enabled: dict[str, float], disabled: dict[str, float]) -> dict[str, float]:
    result: dict[str, float] = {}
    for metric in ("rmse_z_m", "ate_rmse_m", "final_position_error_m"):
        result[f"delta_{metric}_abs"] = enabled[metric] - disabled[metric]
        result[f"delta_{metric}_pct"] = (
            enabled[metric] / disabled[metric] - 1.0
        ) * 100.0
    return result


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
        "gravity_direction_observation": "sensor_msgs/Imu.orientation, 2D Unit3 tangent residual",
        "gravity_direction_sigma_rad": 0.03490658503988659,
        "structural_validation": "PASS",
        "runs": {},
        "contrasts": {},
    }

    for run_name in RUNS:
        time, estimate = load_odometry(root / run_name / "odometry.csv")
        valid = (time >= gt_time[0]) & (time <= gt_time[-1])
        time, estimate = time[valid], estimate[valid]
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
        result["runs"][run_name] = {
            "frames": int(len(time)),
            "duration_s": float(time[-1] - time[0]),
            "gt_arc_length_m": float(
                np.linalg.norm(np.diff(truth, axis=0), axis=1).sum()
            ),
            "rmse_z_m": float(np.sqrt(np.mean(error[:, 2] ** 2))),
            "ate_rmse_m": float(np.sqrt(np.mean(error_norm**2))),
            "final_position_error_m": float(error_norm[-1]),
        }

    runs = result["runs"]
    result["contrasts"] = {
        "direction_factor_with_fixed_gravity": contrast(
            runs["FG-BA_D1"], runs["FG-BA_D0"]
        ),
        "direction_factor_with_online_gravity": contrast(
            runs["GE-BA_D1"], runs["GE-BA_D0"]
        ),
        "online_vs_fixed_gravity_without_direction_factor": contrast(
            runs["GE-BA_D0"], runs["FG-BA_D0"]
        ),
        "online_vs_fixed_gravity_with_direction_factor": contrast(
            runs["GE-BA_D1"], runs["FG-BA_D1"]
        ),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
