#!/usr/bin/env python3
"""Collect one admissible full-length M2DGR LIO-SAM 2x2 ablation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

from collect_liosam_pilot import VARIANTS, load_gt, load_odometry, rigid_alignment


def main() -> int:
    if len(sys.argv) != 5:
        print(
            f"usage: {sys.argv[0]} <run-root> <sequence-name> <gt.txt> <output.json>",
            file=sys.stderr,
        )
        return 2

    root = Path(sys.argv[1])
    sequence = sys.argv[2]
    gt_path = Path(sys.argv[3])
    output_path = Path(sys.argv[4])
    gt_time, gt_position = load_gt(gt_path)
    result: dict[str, object] = {
        "status": "full_sequence_valid",
        "sequence": sequence,
        "playback_rate": 0.5,
        "alignment": "rigid SE(3), first 10 s",
        "runs": {},
    }

    for variant in VARIANTS:
        time, estimate = load_odometry(root / variant / "odometry.csv")
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
        result["runs"][variant] = {
            "frames": int(len(time)),
            "duration_s": float(time[-1] - time[0]),
            "gt_arc_length_m": float(
                np.linalg.norm(np.diff(truth, axis=0), axis=1).sum()
            ),
            "rmse_z_m": float(np.sqrt(np.mean(error[:, 2] ** 2))),
            "ate_rmse_m": float(np.sqrt(np.mean(error_norm**2))),
            "final_position_error_m": float(error_norm[-1]),
        }

    baseline = result["runs"]["FG-BA"]
    for run in result["runs"].values():
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
