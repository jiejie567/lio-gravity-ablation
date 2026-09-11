#!/usr/bin/env python3
"""Collect matched Online/Warm-FixG21 APE traces from existing runs.

The plotted contrast uses one rigid transform per matched pair, fitted to the
Online control with the paper's 10 s / 30 m FAST-LIO2 protocol and then applied
unchanged to both branches.  This preserves the bit-identical pre-switch
history.  Paper metrics are independently re-evaluated with their usual
per-run alignment and checked exactly against report/summary.json.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial.transform import Rotation


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import analyze  # noqa: E402
import collect_metrics  # noqa: E402


OUT = ROOT / "report" / "matched_ape.json"
REPEATS = (("r1", ""), ("r2", "_r2"), ("r3", "_r3"))
SPECS = {
    "vehicle": {
        "base": "ntu_day_10",
        "clean": "ntu_day_10_os1",
        "dropout": "ntu_day_10_drop3x20",
    },
    "handheld": {
        "base": "tuhh_day_04",
        "clean": "tuhh_day_04_os1",
        "dropout": "tuhh_day_04_drop5x20",
    },
}
WINDOW_BEFORE_SWITCH_S = 2.0
GAP_DETECTION_S = 0.5


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_pose(
    path: Path,
    ground_truth: dict[str, np.ndarray],
    estimator_to_body: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    frame = pd.read_csv(path).dropna()
    time = frame.t.to_numpy()
    valid, truth, _ = analyze.interp_gt(ground_truth, time)
    time = time[valid]
    position = frame[["px", "py", "pz"]].to_numpy()[valid]
    orientation = Rotation.from_quat(
        frame[["qx", "qy", "qz", "qw"]].to_numpy()[valid]
    )
    position = position + orientation.apply(estimator_to_body[:3])
    return time, position, truth


def alignment(
    time: np.ndarray, position: np.ndarray, truth: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    arc = np.concatenate(
        ([0.0], np.cumsum(np.linalg.norm(np.diff(truth, axis=0), axis=1)))
    )
    count = max(
        10,
        int(np.searchsorted(time, time[0] + 10.0)),
        int(np.searchsorted(arc, 30.0)),
    )
    count = min(count, len(time) - 1)
    return analyze.umeyama_rigid(position[:count], truth[:count])


def metrics_with_own_alignment(
    time: np.ndarray, position: np.ndarray, truth: np.ndarray
) -> tuple[float, float]:
    rotation, translation = alignment(time, position, truth)
    error = position @ rotation.T + translation - truth
    return (
        float(np.sqrt(np.mean(error[:, 2] ** 2))),
        float(np.sqrt(np.mean(np.linalg.norm(error, axis=1) ** 2))),
    )


def collect_pair(
    sequence: str,
    suffix: str,
    ground_truth: dict[str, np.ndarray],
    estimator_to_body: np.ndarray,
    summary: dict,
) -> dict[str, object]:
    online_name = f"A_warm21{suffix}"
    fixed_name = f"WarmFixG21C{suffix}"
    run_root = ROOT / "results" / sequence
    online_path = run_root / online_name / "state_log.csv"
    fixed_path = run_root / fixed_name / "state_log.csv"
    event_path = run_root / fixed_name / "warm_fixg_event.csv"
    event_frame = pd.read_csv(event_path).dropna()
    if len(event_frame) != 1:
        raise RuntimeError(f"{sequence}/{fixed_name}: expected one switch event")
    event = event_frame.iloc[0]

    online_time, online_position, truth = load_pose(
        online_path, ground_truth, estimator_to_body
    )
    fixed_time, fixed_position, fixed_truth = load_pose(
        fixed_path, ground_truth, estimator_to_body
    )
    if not np.array_equal(online_time, fixed_time):
        raise RuntimeError(f"{sequence}/{fixed_name}: correction timestamps differ")
    if not np.array_equal(truth, fixed_truth):
        raise RuntimeError(f"{sequence}/{fixed_name}: interpolated truth differs")

    snapshot = float(event.snapshot_lidar_time)
    activation = float(event.activation_lidar_time)
    trigger = int(np.searchsorted(online_time, activation))
    if trigger <= 0 or trigger >= len(online_time):
        raise RuntimeError(f"{sequence}/{fixed_name}: invalid activation index")
    if abs(float(online_time[trigger - 1]) - snapshot) > 2e-6:
        raise RuntimeError(f"{sequence}/{fixed_name}: snapshot is not preceding scan")

    online_raw = pd.read_csv(online_path).dropna()
    fixed_raw = pd.read_csv(fixed_path).dropna()
    raw_trigger = int(np.searchsorted(online_raw.t.to_numpy(), activation))
    if not np.array_equal(
        online_raw.iloc[:raw_trigger].to_numpy(),
        fixed_raw.iloc[:raw_trigger].to_numpy(),
    ):
        raise RuntimeError(f"{sequence}/{fixed_name}: pre-switch prefix differs")

    # Common transform: the displayed difference is a paired trajectory
    # contrast, not the difference between two independently chosen frames.
    rotation, translation = alignment(online_time, online_position, truth)
    online_error = online_position @ rotation.T + translation - truth
    fixed_error = fixed_position @ rotation.T + translation - truth
    online_ape = np.linalg.norm(online_error, axis=1)
    fixed_ape = np.linalg.norm(fixed_error, axis=1)
    contrast = fixed_ape - online_ape
    relative_time = online_time - snapshot

    prefix = relative_time < 0.0
    if np.max(np.abs(contrast[prefix])) > 1e-12:
        raise RuntimeError(f"{sequence}/{fixed_name}: nonzero pre-switch APE contrast")

    # Exact cross-check against the paper's authoritative scalar metrics.
    for name, time, position, target in (
        (online_name, online_time, online_position, "online"),
        (fixed_name, fixed_time, fixed_position, "fixed"),
    ):
        calculated = metrics_with_own_alignment(time, position, truth)
        reference = summary[sequence]["runs"][name]
        expected = (float(reference["rmse_z_m"]), float(reference["ate_rmse_m"]))
        if not np.allclose(calculated, expected, rtol=0.0, atol=1e-12):
            raise RuntimeError(
                f"{sequence}/{name}: scalar metric cross-check failed: "
                f"{calculated} != {expected}"
            )

    return {
        "time_s": relative_time,
        "ape_contrast_m": contrast,
        "snapshot_s": snapshot,
        "activation_s": activation,
        "support_s": float(relative_time[-1]),
        "sources": {
            "online": {
                "path": str(online_path.relative_to(ROOT)),
                "sha256": sha256(online_path),
            },
            "warm_fixg21": {
                "path": str(fixed_path.relative_to(ROOT)),
                "sha256": sha256(fixed_path),
            },
            "event": {
                "path": str(event_path.relative_to(ROOT)),
                "sha256": sha256(event_path),
            },
        },
        "metric_crosscheck": True,
    }


def summarize_condition(records: list[dict[str, object]], horizon: float) -> dict:
    reference_time = np.asarray(records[0]["time_s"])
    for record in records[1:]:
        if not np.allclose(
            np.asarray(record["time_s"]), reference_time, rtol=0.0, atol=2e-6
        ):
            raise RuntimeError("repeat correction timestamps are not paired")
    keep = (reference_time >= -WINDOW_BEFORE_SWITCH_S) & (reference_time <= horizon)
    time = reference_time[keep]
    values = np.stack(
        [np.asarray(record["ape_contrast_m"])[keep] for record in records]
    )
    median = np.median(values, axis=0)
    low = np.min(values, axis=0)
    high = np.max(values, axis=0)

    breaks = np.flatnonzero(np.diff(time) > GAP_DETECTION_S)
    starts = np.concatenate(([0], breaks + 1))
    stops = np.concatenate((breaks + 1, [len(time)]))
    stride = max(1, int(math.ceil(len(time) / 900)))
    segments = []
    for start, stop in zip(starts, stops):
        indices = np.arange(start, stop, stride, dtype=int)
        if not len(indices) or indices[-1] != stop - 1:
            indices = np.append(indices, stop - 1)
        segments.append(
            {
                "time_s": time[indices].tolist(),
                "median_m": median[indices].tolist(),
                "range_low_m": low[indices].tolist(),
                "range_high_m": high[indices].tolist(),
            }
        )
    gaps = [
        {"last_correction_s": float(time[index]),
         "first_return_s": float(time[index + 1])}
        for index in breaks
    ]
    return {
        "segments": segments,
        "gaps": gaps,
        "repeat_count": len(records),
        "display_stride": stride,
        "sources": [record["sources"] for record in records],
        "metric_crosscheck": all(bool(record["metric_crosscheck"]) for record in records),
    }


def main() -> None:
    summary = json.loads((ROOT / "report" / "summary.json").read_text())["sequences"]
    warm = json.loads((ROOT / "report" / "warm_fixg21.json").read_text())
    if warm.get("schema_version", 0) < 2:
        raise RuntimeError("warm_fixg21.json predates the matched repeat audit")

    raw: dict[str, dict[str, list[dict[str, object]]]] = {}
    support = []
    for platform, spec in SPECS.items():
        ground_truth = analyze.load_gt_tum(
            ROOT / f"data/mcd/{spec['base']}/gt/pose_inW.csv"
        )
        estimator_to_body = np.asarray(
            collect_metrics.SEQS[spec["clean"]]["est2body"], dtype=float
        )
        raw[platform] = {}
        for condition in ("clean", "dropout"):
            sequence = spec[condition]
            records = []
            for _, suffix in REPEATS:
                records.append(
                    collect_pair(
                        sequence,
                        suffix,
                        ground_truth,
                        estimator_to_body,
                        summary,
                    )
                )
            raw[platform][condition] = records
            support.extend(float(record["support_s"]) for record in records)

    # Use the largest round-ten-second interval shared by every trace.  The
    # horizon is therefore data-derived rather than selected for appearance.
    common_horizon = 10.0 * math.floor(min(support) / 10.0)
    if common_horizon <= 0.0:
        raise RuntimeError("matched APE traces have no common positive support")

    trajectories = {}
    for platform, spec in SPECS.items():
        dropout_report = warm["trajectories"][platform]["dropout"]
        if dropout_report["sequence"] != spec["dropout"]:
            raise RuntimeError(f"{platform}: warm-switch report sequence mismatch")
        trajectories[platform] = {
            "clean_sequence": spec["clean"],
            "dropout_sequence": spec["dropout"],
            "dropout_label": warm["trajectories"][platform]["dropout_label"],
            "clean": summarize_condition(raw[platform]["clean"], common_horizon),
            "dropout": summarize_condition(
                raw[platform]["dropout"], common_horizon
            ),
        }

    report = {
        "schema_version": 1,
        "status": "complete_existing_results_only",
        "metric": "paired absolute position error contrast, Warm FixG21 minus Online",
        "alignment": (
            "one rigid SE(3) transform per matched pair, fitted to Online over "
            "the first interval covering both 10 s and 30 m, then shared by both branches"
        ),
        "selection": (
            "three serial pairs at the original preregistered switch phase; "
            "common horizon is the largest whole 10 s supported by every trace"
        ),
        "common_horizon_s": common_horizon,
        "trajectories": trajectories,
    }
    OUT.write_text(json.dumps(report, indent=2) + "\n")
    print(f"matched APE report -> {OUT}")


if __name__ == "__main__":
    main()
