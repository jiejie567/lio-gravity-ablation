#!/usr/bin/env python3
"""Collect the matched Online -> Warm FixG21 active-subspace experiment.

All metric values come from report/summary.json.  State and event logs are used
only to re-check the causal matching and to record the intervention structure.
The conditional covariance projection is the primary intervention; the vehicle
marginal projection is retained only as an implementation-validity sensitivity.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "report" / "warm_fixg21.json"
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
        "requested_switch_s": 17.0,
        "dropout_label": "3 s/20 s",
    },
    "handheld": {
        "clean": "tuhh_day_04_os1",
        "dropout": "tuhh_day_04_drop5x20",
        "requested_switch_s": 15.0,
        "dropout_label": "5 s/20 s",
    },
}


def read_meta(path: Path) -> dict[str, str]:
    result = {}
    for line in path.read_text().splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            result[key.strip()] = value.strip()
    return result


def metrics_for(records: dict, run: str) -> dict[str, float]:
    return {key: float(records[run][key]) for key in METRICS}


def effect(treatment: dict[str, float], control: dict[str, float]) -> dict:
    return {
        key: {
            "absolute": treatment[key] - control[key],
            "percent": 100.0 * (treatment[key] / control[key] - 1.0),
        }
        for key in METRICS
    }


def collect_condition(
    summary: dict,
    sequence: str,
    include_marginal: bool,
    online_run: str = "A_warm21",
    warm_run: str = "WarmFixG21C",
) -> dict:
    seq_dir = ROOT / "results" / sequence
    online_dir = seq_dir / online_run
    warm_dir = seq_dir / warm_run
    online = pd.read_csv(online_dir / "state_log.csv").dropna()
    warm = pd.read_csv(warm_dir / "state_log.csv").dropna()
    event_frame = pd.read_csv(warm_dir / "warm_fixg_event.csv").dropna()
    if len(event_frame) != 1:
        raise RuntimeError(f"{sequence}: expected one switch event, got {len(event_frame)}")
    event = event_frame.iloc[0]

    if len(online) != len(warm):
        raise RuntimeError(f"{sequence}: frame mismatch")
    if not np.array_equal(online.t.to_numpy(), warm.t.to_numpy()):
        raise RuntimeError(f"{sequence}: correction timestamp mismatch")

    activation = float(event.activation_lidar_time)
    snapshot = float(event.snapshot_lidar_time)
    trigger = int(np.searchsorted(warm.t.to_numpy(), activation))
    if trigger <= 0 or trigger >= len(warm):
        raise RuntimeError(f"{sequence}: invalid trigger row {trigger}")
    if not np.array_equal(online.iloc[:trigger].to_numpy(), warm.iloc[:trigger].to_numpy()):
        raise RuntimeError(f"{sequence}: pre-switch states are not bit-identical")
    if abs(float(warm.t.iloc[trigger - 1]) - snapshot) > 2e-6:
        raise RuntimeError(f"{sequence}: snapshot is not the preceding correction")
    if not np.all(online.active_dof.to_numpy() == 23):
        raise RuntimeError(f"{sequence}: Online control did not remain 23D")
    if not np.all(warm.active_dof.iloc[:trigger].to_numpy() == 23):
        raise RuntimeError(f"{sequence}: Warm branch reduced before the switch")
    if not np.all(warm.active_dof.iloc[trigger:].to_numpy() == 21):
        raise RuntimeError(f"{sequence}: Warm branch is not 21D after the switch")
    if str(event.projection) != "conditional":
        raise RuntimeError(f"{sequence}: primary projection is not conditional")

    gravity = event[["gx", "gy", "gz"]].to_numpy(dtype=float)
    warm_g = warm[["gx", "gy", "gz"]].to_numpy()
    frozen_span = float(np.max(np.abs(warm_g[trigger - 1 :] - gravity)))
    if frozen_span > 1e-9:
        raise RuntimeError(f"{sequence}: fixed gravity moved by {frozen_span:.3e}")
    if float(event.projected_min_eig) <= 0.0:
        raise RuntimeError(f"{sequence}: projected covariance is not positive definite")

    binary = ROOT / "catkin_ws/devel/lib/fast_lio/fastlio_mapping"
    expected_sha = hashlib.sha1(binary.read_bytes()).hexdigest()[:12]
    for run_dir in (online_dir, warm_dir):
        meta = read_meta(run_dir / "run_meta.txt")
        if meta.get("fastlio_binary_sha1") != expected_sha:
            raise RuntimeError(f"{sequence}: stale or mismatched binary fingerprint")

    records = summary[sequence]["runs"]
    online_metrics = metrics_for(records, online_run)
    warm_metrics = metrics_for(records, warm_run)
    result = {
        "sequence": sequence,
        "runs": {"online": online_run, "warm_fixg21": warm_run},
        "frames": len(warm),
        "event": {
            "requested_elapsed_s": float(event.requested_elapsed_s),
            "snapshot_elapsed_s": float(event.snapshot_elapsed_s),
            "activation_elapsed_s": float(event.activation_elapsed_s),
            "correction_gap_s": activation - snapshot,
            "gravity_m_s2": gravity.tolist(),
            "accelerometer_bias_m_s2": event[["bax", "bay", "baz"]]
            .to_numpy(dtype=float)
            .tolist(),
            "pre_switch_gravity_covariance": [
                [float(event.pgg00), float(event.pgg01)],
                [float(event.pgg01), float(event.pgg11)],
            ],
            "pre_switch_state_gravity_cross_covariance_fro": float(event.pxg_fro),
            "projected_active_covariance_min_eigenvalue": float(event.projected_min_eig),
        },
        "structure": {
            "matched_frames": True,
            "matched_correction_timestamps": True,
            "bit_identical_pre_switch_prefix": True,
            "snapshot_is_preceding_correction": True,
            "active_dof_before_after": [23, 21],
            "conditional_covariance_projection": True,
            "fixed_gravity_max_abs_deviation": frozen_span,
            "binary_sha1": expected_sha,
        },
        "metrics": {
            "online": online_metrics,
            "warm_fixg21_conditional": warm_metrics,
            "warm_effect_vs_online": effect(warm_metrics, online_metrics),
        },
    }

    if include_marginal:
        marginal_dir = seq_dir / "WarmFixG21M"
        marginal_event = pd.read_csv(marginal_dir / "warm_fixg_event.csv").dropna()
        marginal = pd.read_csv(marginal_dir / "state_log.csv").dropna()
        if len(marginal_event) != 1 or len(marginal) != len(online):
            raise RuntimeError(f"{sequence}: invalid marginal-projection sensitivity run")
        if not np.array_equal(marginal.t.to_numpy(), online.t.to_numpy()):
            raise RuntimeError(f"{sequence}: marginal sensitivity timestamps differ")
        marginal_metrics = metrics_for(records, "WarmFixG21M")
        result["implementation_sensitivity"] = {
            "marginal_projection_metrics": marginal_metrics,
            "marginal_effect_vs_online": effect(marginal_metrics, online_metrics),
            "interpretation": (
                "Retaining P_xx while declaring the snapshot gravity exact is not "
                "the primary intervention; its clean divergence is an implementation-"
                "validity counterexample, not evidence about fixed gravity."
            ),
        }
    return result


def interaction_for(clean: dict, dropout: dict) -> dict:
    interaction = {}
    for metric in METRICS:
        clean_effect = clean["metrics"]["warm_effect_vs_online"][metric]
        dropout_effect = dropout["metrics"]["warm_effect_vs_online"][metric]
        interaction[metric] = {
            "absolute_difference_in_differences": (
                dropout_effect["absolute"] - clean_effect["absolute"]
            ),
            "effect_difference_percentage_points": (
                dropout_effect["percent"] - clean_effect["percent"]
            ),
        }
    return interaction


def summarize_values(values: list[float]) -> dict:
    array = np.asarray(values, dtype=float)
    return {
        "n": int(array.size),
        "median": float(np.median(array)),
        "range": [float(array.min()), float(array.max())],
    }


def summarize_pairs(pairs: list[dict]) -> dict:
    result = {"clean_effect": {}, "dropout_effect": {}, "interaction": {}}
    for metric in METRICS:
        for condition in ("clean", "dropout"):
            effects = [
                pair[condition]["metrics"]["warm_effect_vs_online"][metric]
                for pair in pairs
            ]
            result[f"{condition}_effect"][metric] = {
                "absolute": summarize_values([item["absolute"] for item in effects]),
                "percent": summarize_values([item["percent"] for item in effects]),
            }
        interactions = [pair["interaction"][metric] for pair in pairs]
        result["interaction"][metric] = {
            "absolute_difference_in_differences": summarize_values([
                item["absolute_difference_in_differences"] for item in interactions
            ]),
            "effect_difference_percentage_points": summarize_values([
                item["effect_difference_percentage_points"] for item in interactions
            ]),
        }
    return result


def main() -> None:
    summary = json.loads((ROOT / "report" / "summary.json").read_text())["sequences"]
    report = {
        "schema_version": 2,
        "design": {
            "name": "Matched Online-to-Warm-FixG21 active-subspace intervention",
            "intervention": (
                "At a pre-specified time, snapshot the Online gravity mean, condition "
                "the active covariance on that value, and continue with a 21D local "
                "error-state update while preserving the full pre-switch history."
            ),
            "causal_control": (
                "The clean and dropout branches use the same trigger, Online state, "
                "map, covariance, and bit-identical pre-switch trajectory; only the "
                "subsequent LiDAR-correction regime differs."
            ),
            "primary_projection": "conditional (Schur complement)",
            "inference": (
                "Three serial pairs at the original phase plus two shifted phases "
                "per trajectory; effects remain trajectory-level and are not pooled"
            ),
        },
        "trajectories": {},
    }

    for label, spec in SPECS.items():
        include_marginal = label == "vehicle"
        clean = collect_condition(summary, spec["clean"], include_marginal)
        dropout = collect_condition(summary, spec["dropout"], include_marginal)
        interaction = interaction_for(clean, dropout)

        pairs = []
        for repeat, suffix in (("r1", ""), ("r2", "_r2"), ("r3", "_r3")):
            repeat_clean = collect_condition(
                summary,
                spec["clean"],
                False,
                f"A_warm21{suffix}",
                f"WarmFixG21C{suffix}",
            )
            repeat_dropout = collect_condition(
                summary,
                spec["dropout"],
                False,
                f"A_warm21{suffix}",
                f"WarmFixG21C{suffix}",
            )
            pairs.append({
                "repeat": repeat,
                "clean": repeat_clean,
                "dropout": repeat_dropout,
                "interaction": interaction_for(repeat_clean, repeat_dropout),
            })

        phase_entries = [{
            "dropout_start_s": spec["requested_switch_s"],
            "replicated": True,
            "interaction_summary": summarize_pairs(pairs)["interaction"],
        }]
        for start in (12, 22):
            phase_clean = collect_condition(
                summary,
                spec["clean"],
                False,
                "A_warm21",
                f"WarmFixG21C_s{start}",
            )
            phase_dropout = collect_condition(
                summary,
                f"{spec['dropout']}_s{start}",
                False,
            )
            phase_entries.append({
                "dropout_start_s": start,
                "replicated": False,
                "clean": phase_clean,
                "dropout": phase_dropout,
                "interaction": interaction_for(phase_clean, phase_dropout),
            })

        phase_summary = {}
        for metric in METRICS:
            values = [
                phase_entries[0]["interaction_summary"][metric][
                    "absolute_difference_in_differences"
                ]["median"]
            ]
            values.extend(
                entry["interaction"][metric]["absolute_difference_in_differences"]
                for entry in phase_entries[1:]
            )
            phase_summary[metric] = {
                "absolute_difference_in_differences": summarize_values(values),
                "all_positive": bool(all(value > 0.0 for value in values)),
                "all_negative": bool(all(value < 0.0 for value in values)),
            }
        report["trajectories"][label] = {
            "requested_switch_s": spec["requested_switch_s"],
            "dropout_label": spec["dropout_label"],
            "clean": clean,
            "dropout": dropout,
            "warm_fixg21_by_dropout_interaction": interaction,
            "repeatability": {
                "pairs": pairs,
                "summary": summarize_pairs(pairs),
            },
            "phase_robustness": {
                "phases": phase_entries,
                "summary": phase_summary,
            },
        }

    OUT.write_text(json.dumps(report, indent=2) + "\n")
    print(f"warm FixG21 report -> {OUT}")


if __name__ == "__main__":
    main()
