#!/usr/bin/env python3
"""Collect the formal LIO-SAM gravity-direction-factor ablation.

This writes a separate machine-readable source because the experiment varies
an added observation, not the g/b_a state structure summarized in summary.json.
Only roots that have already passed validate_liosam_direction_sweep.py should
be collected.
"""

from __future__ import annotations

import csv
import json
import math
import statistics
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation


ROOT = Path(__file__).resolve().parent.parent
LEVELS = ("off", "s0p5", "s2", "s5")
VARIANTS = ("FG-BA", "GE-BA")
POS = tuple(f"field.pose.pose.position.{axis}" for axis in "xyz")
QUAT = tuple(f"field.pose.pose.orientation.{axis}" for axis in "xyzw")
T_LIDAR_BODY_HANDHELD = np.array(
    [-0.04894521120494695, -0.03126929060348084, -0.01755515794222565]
)


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def load_estimate(path: Path, dataset: str) -> tuple[np.ndarray, np.ndarray]:
    rows = load_rows(path)
    time = np.array([float(row["%time"]) * 1e-9 for row in rows])
    position = np.array([[float(row[field]) for field in POS] for row in rows])
    if dataset == "mcd":
        quaternion = np.array([[float(row[field]) for field in QUAT] for row in rows])
        position += Rotation.from_quat(quaternion).apply(T_LIDAR_BODY_HANDHELD)
    return time, position


def load_gt(path: Path, dataset: str) -> tuple[np.ndarray, np.ndarray]:
    if dataset == "m2dgr":
        values = np.loadtxt(path)
        return values[:, 0], values[:, 1:4]
    values = np.genfromtxt(path, delimiter=",", names=True)
    return values["t"], np.column_stack((values["x"], values["y"], values["z"]))


def rigid_alignment(source: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    source_mean = source.mean(axis=0)
    target_mean = target.mean(axis=0)
    covariance = (target - target_mean).T @ (source - source_mean)
    left, _, right_t = np.linalg.svd(covariance)
    correction = np.diag([1.0, 1.0, np.sign(np.linalg.det(left @ right_t))])
    rotation = left @ correction @ right_t
    translation = target_mean - rotation @ source_mean
    return rotation, translation


def direction_stats(path: Path) -> dict[str, float | int] | None:
    if not path.is_file():
        return None
    rows = load_rows(path)
    if not rows:
        return None
    pre = [float(row["pre_residual_deg"]) for row in rows]
    post = [float(row["post_residual_deg"]) for row in rows]
    age = [float(row["measurement_age_s"]) for row in rows]
    return {
        "factors": len(rows),
        "median_pre_residual_deg": statistics.median(pre),
        "median_post_residual_deg": statistics.median(post),
        "p95_post_residual_deg": float(np.percentile(post, 95)),
        "max_measurement_age_s": max(age),
    }


def evaluate_run(
    run: Path,
    dataset: str,
    gt_time: np.ndarray,
    gt_position: np.ndarray,
) -> dict[str, object]:
    time, estimate = load_estimate(run / "odometry.csv", dataset)
    valid = (time >= gt_time[0]) & (time <= gt_time[-1])
    time, estimate = time[valid], estimate[valid]
    if len(time) < 10:
        raise RuntimeError(f"{run}: insufficient GT overlap")
    truth = np.column_stack(
        [np.interp(time, gt_time, gt_position[:, axis]) for axis in range(3)]
    )
    align_count = max(10, int(np.searchsorted(time, time[0] + 10.0)))
    rotation, translation = rigid_alignment(estimate[:align_count], truth[:align_count])
    aligned = estimate @ rotation.T + translation
    error = aligned - truth
    error_norm = np.linalg.norm(error, axis=1)
    gt_arc = float(np.linalg.norm(np.diff(truth, axis=0), axis=1).sum())
    estimate_arc = float(np.linalg.norm(np.diff(aligned, axis=0), axis=1).sum())
    arc_ratio = estimate_arc / gt_arc
    if not 0.6 <= arc_ratio <= 1.6:
        raise RuntimeError(f"{run}: arc-length gate failed ({arc_ratio:.3f})")
    rmse_z = float(np.sqrt(np.mean(error[:, 2] ** 2)))
    ate = float(np.sqrt(np.mean(error_norm ** 2)))
    result: dict[str, object] = {
        "frames": int(len(time)),
        "duration_s": float(time[-1] - time[0]),
        "gt_arc_length_m": gt_arc,
        "estimate_to_gt_arc_ratio": arc_ratio,
        "rmse_z_m": rmse_z,
        "ate_rmse_m": ate,
        "rmse_z_mm_per_100m": rmse_z / gt_arc * 100000.0,
        "ate_mm_per_100m": ate / gt_arc * 100000.0,
        "final_position_error_m": float(error_norm[-1]),
    }
    stats = direction_stats(run / "gravity_direction.csv")
    if stats is not None:
        result["direction_factor"] = stats
    return result


def collect_sequence(
    name: str,
    root: Path,
    dataset: str,
    gt_path: Path,
    levels: tuple[str, ...],
) -> dict[str, object]:
    gt_time, gt_position = load_gt(gt_path, dataset)
    runs: dict[str, dict[str, object]] = {}
    for variant in VARIANTS:
        for level in levels:
            run_name = f"{variant}_{level}"
            runs[run_name] = evaluate_run(root / run_name, dataset, gt_time, gt_position)
        baseline = runs[f"{variant}_off"]
        for level in levels:
            run = runs[f"{variant}_{level}"]
            for metric, label in (("rmse_z_m", "rmse_z"), ("ate_rmse_m", "ate")):
                absolute = float(run[metric]) - float(baseline[metric])
                run[f"delta_{label}_m_vs_off"] = absolute
                run[f"delta_{label}_pct_vs_off"] = absolute / float(baseline[metric]) * 100.0
    return {
        "sequence": name,
        "dataset": dataset,
        "levels": list(levels),
        "runs": runs,
    }


def summarize_valid_runs(
    paths: list[Path], dataset: str, gt_path: Path
) -> dict[str, object]:
    gt_time, gt_position = load_gt(gt_path, dataset)
    evaluated = [evaluate_run(path, dataset, gt_time, gt_position) for path in paths]
    summary: dict[str, object] = {
        "valid_runs": len(evaluated),
        "run_paths": [str(path.relative_to(ROOT)) for path in paths],
        "runs": evaluated,
    }
    for metric in ("rmse_z_m", "ate_rmse_m"):
        values = [float(run[metric]) for run in evaluated]
        summary[metric] = {
            "values": values,
            "median": statistics.median(values),
            "range": [min(values), max(values)],
            "relative_range_pct": (max(values) / min(values) - 1.0) * 100.0,
        }
    return summary


def invalid_run_summary(path: Path) -> dict[str, object]:
    state = load_rows(path / "state_log.csv")
    odometry = load_rows(path / "odometry.csv")
    factor = load_rows(path / "gravity_direction.csv")
    launch = (path / "launch.log").read_text(errors="replace")
    return {
        "path": str(path.relative_to(ROOT)),
        "status": "invalid_stability_outcome_not_accuracy_run",
        "state_rows": len(state),
        "odometry_rows": len(odometry),
        "factor_rows": len(factor),
        "large_velocity_resets": launch.count("Large velocity"),
    }


def paired_repeat_effects(
    pairs: list[tuple[str, Path, Path]], dataset: str, gt_path: Path
) -> dict[str, object]:
    gt_time, gt_position = load_gt(gt_path, dataset)
    effects: list[dict[str, object]] = []
    for repeat, off_path, enabled_path in pairs:
        off = evaluate_run(off_path, dataset, gt_time, gt_position)
        enabled = evaluate_run(enabled_path, dataset, gt_time, gt_position)
        item: dict[str, object] = {"repeat": repeat, "off": off, "s2": enabled}
        for metric, label in (("rmse_z_m", "rmse_z"), ("ate_rmse_m", "ate")):
            difference = float(enabled[metric]) - float(off[metric])
            item[f"delta_{label}_m"] = difference
            item[f"delta_{label}_pct"] = difference / float(off[metric]) * 100.0
        effects.append(item)
    return {
        "paired_repeats": len(effects),
        "effects": effects,
        "delta_rmse_z_pct_range": [
            min(float(item["delta_rmse_z_pct"]) for item in effects),
            max(float(item["delta_rmse_z_pct"]) for item in effects),
        ],
        "delta_ate_pct_range": [
            min(float(item["delta_ate_pct"]) for item in effects),
            max(float(item["delta_ate_pct"]) for item in effects),
        ],
    }


def repeated_factorial(
    root: Path, dataset: str, gt_path: Path, repeats: tuple[str, ...]
) -> dict[str, object]:
    """Collect a paired state x direction-factor factorial within one trajectory."""
    gt_time, gt_position = load_gt(gt_path, dataset)
    cells: dict[str, list[dict[str, object]]] = {
        f"{variant}_{level}": []
        for variant in VARIANTS
        for level in ("off", "s2")
    }
    paired: list[dict[str, object]] = []
    for repeat in repeats:
        run_metrics: dict[str, dict[str, object]] = {}
        for variant in VARIANTS:
            for level in ("off", "s2"):
                cell = f"{variant}_{level}"
                metrics = evaluate_run(
                    root / f"{cell}_{repeat}", dataset, gt_time, gt_position
                )
                cells[cell].append(metrics)
                run_metrics[cell] = metrics

        item: dict[str, object] = {"repeat": repeat, "runs": run_metrics}
        for metric, label in (("rmse_z_m", "rmse_z"), ("ate_rmse_m", "ate")):
            effects: dict[str, float] = {}
            for variant in VARIANTS:
                off = float(run_metrics[f"{variant}_off"][metric])
                enabled = float(run_metrics[f"{variant}_s2"][metric])
                effects[variant] = (enabled / off - 1.0) * 100.0
                item[f"{variant}_{label}_factor_effect_pct"] = effects[variant]
            item[f"interaction_{label}_percentage_points"] = (
                effects["GE-BA"] - effects["FG-BA"]
            )
            item[f"interaction_{label}_log_ratio"] = math.log(
                (
                    float(run_metrics["GE-BA_s2"][metric])
                    / float(run_metrics["GE-BA_off"][metric])
                )
                /
                (
                    float(run_metrics["FG-BA_s2"][metric])
                    / float(run_metrics["FG-BA_off"][metric])
                )
            )
        paired.append(item)

    summaries: dict[str, object] = {}
    for cell, runs in cells.items():
        summary: dict[str, object] = {"runs": runs}
        for metric in ("rmse_z_m", "ate_rmse_m"):
            values = [float(run[metric]) for run in runs]
            summary[metric] = {
                "values": values,
                "median": statistics.median(values),
                "range": [min(values), max(values)],
            }
        summaries[cell] = summary

    effect_ranges: dict[str, object] = {}
    for variant in VARIANTS:
        for label in ("rmse_z", "ate"):
            values = [
                float(item[f"{variant}_{label}_factor_effect_pct"])
                for item in paired
            ]
            effect_ranges[f"{variant}_{label}_factor_effect_pct"] = {
                "values": values,
                "median": statistics.median(values),
                "range": [min(values), max(values)],
            }
    for label in ("rmse_z", "ate"):
        values = [
            float(item[f"interaction_{label}_percentage_points"])
            for item in paired
        ]
        effect_ranges[f"interaction_{label}_percentage_points"] = {
            "values": values,
            "median": statistics.median(values),
            "range": [min(values), max(values)],
        }

    return {
        "sequence": "m2dgr-hall05-drop5x20",
        "dataset": dataset,
        "paired_repeats": len(repeats),
        "cells": summaries,
        "paired": paired,
        "effects": effect_ranges,
        "accuracy_status": (
            "harmful GE-BA x direction-factor interaction not reproduced: "
            "the 2-deg factor improves both metrics for both state structures; "
            "the rescue is larger with fixed gravity"
        ),
        "inference": (
            "single-trajectory repeated mechanism evidence; repeats are not "
            "independent trajectory units"
        ),
    }


def main() -> int:
    mcd_gt = ROOT / "data/mcd/tuhh_day_04/gt/pose_inW.csv"
    nominal = [
        collect_sequence(
            "m2dgr-hall05",
            ROOT / "results/liosam_direction_full/m2dgr_hall05",
            "m2dgr",
            ROOT / "data/m2dgr/hall_05/gt/gt.txt",
            LEVELS,
        ),
        collect_sequence(
            "mcd-tuhh-day04",
            ROOT / "results/liosam_direction_full/mcd_tuhh_day04",
            "mcd",
            mcd_gt,
            LEVELS,
        ),
    ]
    dropout = [
        collect_sequence(
            f"mcd-tuhh-day04-{dropout}",
            ROOT / f"results/liosam_direction_dropout/mcd_tuhh_day04_{dropout}",
            "mcd",
            mcd_gt,
            ("off", "s2"),
        )
        for dropout in ("drop2x20", "drop3x20", "drop5x20")
    ]
    drop3_root = ROOT / "results/liosam_direction_dropout/mcd_tuhh_day04_drop3x20"
    repeat_root = ROOT / "results/liosam_direction_repeats/mcd_tuhh_day04_drop3x20"
    dropout[1]["accuracy_status"] = (
        "not_identifiable: recovery variability exceeds the paired effect; "
        "one of three FG-BA+s2 attempts failed the stability gate"
    )
    dropout[1]["repeatability"] = {
        "FG-BA_off": summarize_valid_runs(
            [drop3_root / "FG-BA_off", repeat_root / "FG-BA_off_r2", repeat_root / "FG-BA_off_r3"],
            "mcd", mcd_gt,
        ),
        "FG-BA_s2": summarize_valid_runs(
            [drop3_root / "FG-BA_s2", repeat_root / "FG-BA_s2_r3"],
            "mcd", mcd_gt,
        ),
        "FG-BA_s2_invalid": invalid_run_summary(
            ROOT / "quarantine/liosam_direction_drop3_fg_s2_20260825/r1/FG-BA_s2"
        ),
    }

    drop5_root = ROOT / "results/liosam_direction_dropout/mcd_tuhh_day04_drop5x20"
    drop5_repeat = ROOT / "results/liosam_direction_repeats/mcd_tuhh_day04_drop5x20"
    dropout[2]["accuracy_status"] = (
        "GE-BA paired failure replicated twice; FG-BA remains a single descriptive pair"
    )
    dropout[2]["repeatability"] = {
        "GE-BA": paired_repeat_effects(
            [
                ("r1", drop5_root / "GE-BA_off", drop5_root / "GE-BA_s2"),
                ("r2", drop5_repeat / "GE-BA_off_r2", drop5_repeat / "GE-BA_s2_r2"),
            ],
            "mcd", mcd_gt,
        )
    }
    hall05_dropout = repeated_factorial(
        ROOT / "results/liosam_direction_dropout/m2dgr_hall05_drop5x20",
        "m2dgr",
        ROOT / "data/m2dgr/hall_05/gt/gt.txt",
        ("r1", "r2", "r3"),
    )
    result = {
        "status": "descriptive_mechanism_ablation_two_nominal_sequences",
        "inference": (
            "The nominal dose sweep has two sequence units and is descriptive; "
            "dropout levels are interventions on one trajectory, not independent samples."
        ),
        "factor": (
            "AHRS-derived gravity-direction observation added once per LiDAR "
            "correction epoch; no altitude or vertical-velocity observation."
        ),
        "alignment": "rigid SE(3), first 10 s",
        "nominal": nominal,
        "dropout": dropout,
        "hall05_dropout_factorial": hall05_dropout,
    }
    output = ROOT / "report/liosam_direction.json"
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
