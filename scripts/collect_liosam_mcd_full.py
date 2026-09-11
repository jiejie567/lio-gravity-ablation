#!/usr/bin/env python3
"""Collect one admissible full-length MCD LIO-SAM 2x2 ablation.

This is deliberately separate from report/summary.json until at least a second
full sequence exists; one sequence is evidence, not a cross-sequence claim.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

from collect_liosam_mcd_pilot import VARIANTS, align, load_estimate, load_gt


def main() -> int:
    if len(sys.argv) != 6 or sys.argv[2] not in ("atv", "handheld"):
        print(
            f"usage: {sys.argv[0]} <run-root> <atv|handheld> <sequence-name> <gt.csv> <output.json>",
            file=sys.stderr,
        )
        return 2
    root = Path(sys.argv[1])
    setup, sequence = sys.argv[2], sys.argv[3]
    gt_path, output = Path(sys.argv[4]), Path(sys.argv[5])
    gt_time, gt_position = load_gt(gt_path)
    result: dict[str, object] = {
        "status": "full_sequence_valid_single_sequence_not_cross_sequence_claim",
        "sequence": sequence,
        "playback_rate": 0.25,
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
