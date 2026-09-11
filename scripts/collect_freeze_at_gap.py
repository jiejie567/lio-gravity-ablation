#!/usr/bin/env python3
"""Collect the matched late-freeze mechanism experiment.

The intervention stays on the 23D FAST-LIO2 manifold and freezes only the
gravity mean correction after a pre-specified elapsed-time trigger.  It is a
mechanism proxy, not the 21D FixG result.  All manuscript-facing values are
derived from report/summary.json and the audited run logs.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "report" / "freeze_at_gap.json"
METRICS = (
    "rmse_z_m",
    "ate_rmse_m",
    "rmse_roll_deg",
    "rmse_pitch_deg",
)
SPECS = {
    "vehicle": {
        "clean": "ntu_day_10_os1",
        "dropout": "ntu_day_10_drop3x20",
        "requested_freeze_s": 17.0,
        "dropout_label": "3 s/20 s",
    },
    "handheld": {
        "clean": "tuhh_day_04_os1",
        "dropout": "tuhh_day_04_drop5x20",
        "requested_freeze_s": 15.0,
        "dropout_label": "5 s/20 s",
    },
}


def angle_deg(vectors: np.ndarray, reference: np.ndarray) -> np.ndarray:
    numerator = vectors @ reference
    denominator = np.linalg.norm(vectors, axis=1) * np.linalg.norm(reference)
    return np.degrees(np.arccos(np.clip(numerator / denominator, -1.0, 1.0)))


def read_meta(path: Path) -> dict[str, str]:
    meta = {}
    for line in path.read_text().splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
    return meta


def collect_condition(summary: dict, sequence: str) -> dict:
    seq_dir = ROOT / "results" / sequence
    online_dir = seq_dir / "A_gapbranch"
    freeze_dir = seq_dir / "FreezeAtGap"
    online_log = pd.read_csv(online_dir / "state_log.csv").dropna()
    freeze_log = pd.read_csv(freeze_dir / "state_log.csv").dropna()
    event_frame = pd.read_csv(freeze_dir / "freeze_event.csv").dropna()
    if len(event_frame) != 1:
        raise RuntimeError(f"{sequence}: expected one freeze event, got {len(event_frame)}")
    event = event_frame.iloc[0]

    if len(online_log) != len(freeze_log):
        raise RuntimeError(f"{sequence}: frame mismatch")
    if not np.array_equal(online_log["t"].to_numpy(), freeze_log["t"].to_numpy()):
        raise RuntimeError(f"{sequence}: correction timestamp mismatch")

    activation = float(event["activation_lidar_time"])
    snapshot = float(event["snapshot_lidar_time"])
    trigger = int(np.searchsorted(freeze_log["t"].to_numpy(), activation))
    if trigger <= 0 or trigger >= len(freeze_log):
        raise RuntimeError(f"{sequence}: invalid trigger row {trigger}")
    if not np.array_equal(
        online_log.iloc[:trigger].to_numpy(), freeze_log.iloc[:trigger].to_numpy()
    ):
        raise RuntimeError(f"{sequence}: pre-trigger states are not bit-identical")
    if abs(float(freeze_log["t"].iloc[trigger - 1]) - snapshot) > 2e-6:
        raise RuntimeError(f"{sequence}: snapshot is not the preceding correction")

    reference = event[["gx", "gy", "gz"]].to_numpy(dtype=float)
    frozen_g = freeze_log[["gx", "gy", "gz"]].to_numpy()
    frozen_span = float(np.max(np.abs(frozen_g[trigger - 1 :] - reference)))
    if frozen_span > 1e-9:
        raise RuntimeError(f"{sequence}: frozen gravity moved by {frozen_span:.3e}")

    binary = ROOT / "catkin_ws/devel/lib/fast_lio/fastlio_mapping"
    expected_sha = hashlib.sha1(binary.read_bytes()).hexdigest()[:12]
    for run_dir in (online_dir, freeze_dir):
        meta = read_meta(run_dir / "run_meta.txt")
        if meta.get("fastlio_binary_sha1") != expected_sha:
            raise RuntimeError(f"{sequence}: stale or mismatched binary fingerprint")

    records = summary[sequence]["runs"]
    online_metrics = {key: float(records["A_gapbranch"][key]) for key in METRICS}
    freeze_metrics = {key: float(records["FreezeAtGap"][key]) for key in METRICS}
    fixg_metrics = {key: float(records["RED21"][key]) for key in METRICS}
    effects = {
        key: {
            "absolute": freeze_metrics[key] - online_metrics[key],
            "percent": 100.0 * (freeze_metrics[key] / online_metrics[key] - 1.0),
        }
        for key in METRICS
    }
    freeze_vs_fixg = {
        key: {
            "absolute": freeze_metrics[key] - fixg_metrics[key],
            "percent": 100.0 * (freeze_metrics[key] / fixg_metrics[key] - 1.0),
        }
        for key in METRICS
    }

    online_g = online_log[["gx", "gy", "gz"]].to_numpy()
    gravity_motion = angle_deg(online_g[trigger:], reference)
    position_delta = np.linalg.norm(
        online_log[["px", "py", "pz"]].to_numpy()
        - freeze_log[["px", "py", "pz"]].to_numpy(),
        axis=1,
    )

    return {
        "sequence": sequence,
        "frames": len(freeze_log),
        "event": {
            "requested_elapsed_s": float(event["requested_elapsed_s"]),
            "snapshot_elapsed_s": float(event["snapshot_elapsed_s"]),
            "activation_elapsed_s": float(event["activation_elapsed_s"]),
            "correction_gap_s": activation - snapshot,
            "gravity_m_s2": reference.tolist(),
            "accelerometer_bias_m_s2": event[["bax", "bay", "baz"]]
            .to_numpy(dtype=float)
            .tolist(),
        },
        "structure": {
            "matched_frames": True,
            "matched_correction_timestamps": True,
            "bit_identical_pre_trigger_prefix": True,
            "snapshot_is_preceding_correction": True,
            "frozen_gravity_max_abs_deviation": frozen_span,
            "binary_sha1": expected_sha,
        },
        "metrics": {
            "online": online_metrics,
            "freeze_at_gap": freeze_metrics,
            "fixg_from_initialization": fixg_metrics,
            "freeze_effect_vs_online": effects,
            "freeze_effect_vs_fixg": freeze_vs_fixg,
        },
        "diagnostics": {
            "online_gravity_motion_after_snapshot_final_deg": float(gravity_motion[-1]),
            "online_gravity_motion_after_snapshot_max_deg": float(np.max(gravity_motion)),
            "raw_position_separation_first_return_m": float(position_delta[trigger]),
            "raw_position_separation_final_m": float(position_delta[-1]),
            "raw_position_separation_max_m": float(np.max(position_delta[trigger:])),
        },
    }


def main() -> None:
    summary = json.loads((ROOT / "report/summary.json").read_text())["sequences"]
    report = {
        "schema_version": 1,
        "design": {
            "name": "Freeze@Gap matched mechanism proxy",
            "state_manifold": "FAST-LIO2 23D Online manifold",
            "intervention": (
                "snapshot gravity after the last completed correction before the "
                "trigger, then zero subsequent 2D gravity-mean increments"
            ),
            "causal_control": "same elapsed-time trigger on clean and dropout bags",
            "scope": (
                "runtime mean-freeze mechanism proxy; covariance remains 23D and "
                "the result is not a true 21D FixG ablation"
            ),
            "online_during_gap": (
                "gravity has no process dynamics, so its mean is unchanged during "
                "the gap; branch separation can begin only at the return-scan update"
            ),
            "inference": "descriptive matched contrasts on two trajectories; no pooling",
        },
        "trajectories": {},
    }

    for label, spec in SPECS.items():
        clean = collect_condition(summary, spec["clean"])
        dropout = collect_condition(summary, spec["dropout"])
        interaction = {}
        for metric in METRICS:
            clean_effect = clean["metrics"]["freeze_effect_vs_online"][metric]
            dropout_effect = dropout["metrics"]["freeze_effect_vs_online"][metric]
            interaction[metric] = {
                "absolute_difference_in_differences": (
                    dropout_effect["absolute"] - clean_effect["absolute"]
                ),
                "effect_difference_percentage_points": (
                    dropout_effect["percent"] - clean_effect["percent"]
                ),
            }
        report["trajectories"][label] = {
            "requested_freeze_s": spec["requested_freeze_s"],
            "dropout_label": spec["dropout_label"],
            "clean": clean,
            "dropout": dropout,
            "freeze_by_dropout_interaction": interaction,
        }

    OUT.write_text(json.dumps(report, indent=2) + "\n")
    print(f"freeze-at-gap report -> {OUT}")


if __name__ == "__main__":
    main()
