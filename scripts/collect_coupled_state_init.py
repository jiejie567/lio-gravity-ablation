#!/usr/bin/env python3
"""Collect the pre-registered gravity--ba allocation experiment."""

import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd
from scipy.spatial.transform import Rotation


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "report/coupled_state_init.json"
EXPERIMENTS = {
    "vehicle": "ntu_day_10_coupledinit60",
    "handheld": "tuhh_day_04_coupledinit60",
}


def rms_norm(values: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.sum(values * values, axis=1))))


def angle_series(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    first = first / np.linalg.norm(first, axis=1, keepdims=True)
    second = second / np.linalg.norm(second, axis=1, keepdims=True)
    return np.degrees(np.arccos(np.clip(np.sum(first * second, axis=1), -1.0, 1.0)))


def state_terms(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    gravity = frame[["gx", "gy", "gz"]].to_numpy(dtype=float)
    ba = frame[["bax", "bay", "baz"]].to_numpy(dtype=float)
    rotation = Rotation.from_quat(
        frame[["qx", "qy", "qz", "qw"]].to_numpy(dtype=float)
    )
    world_ba = rotation.apply(ba)
    return gravity, world_ba, gravity - world_ba


def relative(value: float, reference: float) -> float:
    return float((value / reference - 1.0) * 100.0)


def summarize_pair(
    base: pd.DataFrame,
    comparison: pd.DataFrame,
    base_metrics: dict,
    comparison_metrics: dict,
) -> dict:
    base_g, base_rba, base_h = state_terms(base)
    comp_g, comp_rba, comp_h = state_terms(comparison)
    dg, drba, dh = comp_g - base_g, comp_rba - base_rba, comp_h - base_h
    denominator = rms_norm(dg) + rms_norm(drba)
    elapsed = base["t"].to_numpy(dtype=float) - float(base["t"].iloc[0])
    tail = elapsed >= elapsed[-1] - 10.0
    position_delta = comparison[["px", "py", "pz"]].to_numpy(dtype=float) - base[
        ["px", "py", "pz"]
    ].to_numpy(dtype=float)
    ba_delta = comparison[["bax", "bay", "baz"]].to_numpy(dtype=float) - base[
        ["bax", "bay", "baz"]
    ].to_numpy(dtype=float)
    gravity_angle = angle_series(base_g, comp_g)
    return {
        "initial": {
            "gravity_angle_to_base_deg": float(gravity_angle[0]),
            "ba_distance_to_base_mps2": float(np.linalg.norm(ba_delta[0])),
            "effective_term_distance_to_base_mps2": float(np.linalg.norm(dh[0])),
        },
        "whole_run": {
            "gravity_component_rms_mps2": rms_norm(dg),
            "rotated_ba_component_rms_mps2": rms_norm(drba),
            "effective_term_rms_mps2": rms_norm(dh),
            "cancellation_ratio": float(rms_norm(dh) / denominator) if denominator else None,
            "direct_position_rms_to_base_m": rms_norm(position_delta),
        },
        "last_10s": {
            "gravity_angle_to_base_deg_median": float(np.median(gravity_angle[tail])),
            "ba_distance_to_base_mps2_median": float(
                np.median(np.linalg.norm(ba_delta[tail], axis=1))
            ),
            "effective_term_distance_to_base_mps2_median": float(
                np.median(np.linalg.norm(dh[tail], axis=1))
            ),
            "position_distance_to_base_m_median": float(
                np.median(np.linalg.norm(position_delta[tail], axis=1))
            ),
        },
        "trajectory_metrics": {
            "rmse_z_m": float(comparison_metrics["rmse_z_m"]),
            "ate_rmse_m": float(comparison_metrics["ate_rmse_m"]),
            "rmse_z_change_pct": relative(
                comparison_metrics["rmse_z_m"], base_metrics["rmse_z_m"]
            ),
            "ate_change_pct": relative(
                comparison_metrics["ate_rmse_m"], base_metrics["ate_rmse_m"]
            ),
        },
    }


def main() -> None:
    for sequence in EXPERIMENTS.values():
        subprocess.run(
            [sys.executable, str(ROOT / "scripts/validate_coupled_state_init.py"), sequence],
            check=True,
        )

    report = {
        "schema": 1,
        "generated_by": "scripts/collect_coupled_state_init.py",
        "status": "completed_structural_gates_pass",
        "planned_runs": 10,
        "included_runs": 10,
        "trajectory_units": 2,
        "question": (
            "Can different online gravity/accelerometer-bias allocations preserve "
            "the propagation-relevant combination and pose?"
        ),
        "intervention": {
            "gravity_tilt_deg": [-2.0, 2.0],
            "paired_rule": "ba1 = ba0 + R0^T (g1 - g0)",
            "invariant_at_boundary": "g1 - R0 ba1 = g0 - R0 ba0",
            "duration_s": 60.0,
            "all_states": "Online g + Online ba",
        },
        "interpretation_boundary": (
            "This tests state allocation and compensation, not absolute ba truth "
            "or the frequency of marginal-state error."
        ),
        "sequences": {},
    }

    for trajectory, sequence in EXPERIMENTS.items():
        root = ROOT / "results" / sequence
        frames = {
            name: pd.read_csv(root / name / "state_log.csv").dropna()
            for name in ("base", "g_p2", "gb_p2", "g_m2", "gb_m2")
        }
        reference_time = frames["base"]["t"].to_numpy(dtype=float)
        if any(
            not np.array_equal(frame["t"].to_numpy(dtype=float), reference_time)
            for frame in frames.values()
        ):
            raise RuntimeError(f"{sequence}: timestamps differ")
        metrics = json.loads((root / "analysis/metrics.json").read_text())["runs"]
        base_metrics = metrics["base"]
        report["sequences"][trajectory] = {
            "result_group": sequence,
            "frames": int(len(frames["base"])),
            "baseline": {
                "rmse_z_m": float(base_metrics["rmse_z_m"]),
                "ate_rmse_m": float(base_metrics["ate_rmse_m"]),
            },
            "plus": {
                "gravity_only": summarize_pair(
                    frames["base"], frames["g_p2"], base_metrics, metrics["g_p2"]
                ),
                "paired": summarize_pair(
                    frames["base"], frames["gb_p2"], base_metrics, metrics["gb_p2"]
                ),
            },
            "minus": {
                "gravity_only": summarize_pair(
                    frames["base"], frames["g_m2"], base_metrics, metrics["g_m2"]
                ),
                "paired": summarize_pair(
                    frames["base"], frames["gb_m2"], base_metrics, metrics["gb_m2"]
                ),
            },
        }

    OUT.write_text(json.dumps(report, indent=1) + "\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
