#!/usr/bin/env python3
"""Collect the true-manifold dynamic-start gravity/bias 2x2 experiment."""

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import collect_dynamic_init as base  # noqa: E402
from validate_dynamic_init_factorial import gt_path_length  # noqa: E402


METHODS = ("A", "RED21", "RED20", "RED18")
LABELS = {
    "A": "Online",
    "RED21": "FixG",
    "RED20": "FixBa",
    "RED18": "FixG+Ba",
}
METRICS = ("rmse_z_m", "ate_rmse_m")


def effect(candidate: float, reference: float) -> dict:
    return {
        "absolute_m": candidate - reference,
        "relative_pct": 100.0 * (candidate / reference - 1.0),
    }


def log_interaction(values: dict[str, float]) -> dict:
    interaction = math.log(values["RED18"] / values["A"])
    interaction -= math.log(values["RED21"] / values["A"])
    interaction -= math.log(values["RED20"] / values["A"])
    return {
        "log_ratio": interaction,
        "relative_pct": 100.0 * math.expm1(interaction),
    }


def source_records() -> list[dict]:
    nominal = json.loads((ROOT / "report" / "dynamic_init.json").read_text())
    stronger = json.loads((ROOT / "report" / "dynamic_init_fast.json").read_text())
    records = []
    for record in nominal["records"]:
        records.append({
            "sequence": record["sequence"],
            "platform": record["platform"],
            "regime": record["regime"],
            "start_sec": record["start_sec"],
            "duration_sec": record["duration_sec"],
            "selection_window": record["selection_window"],
            "selection_source": "report/dynamic_init.json",
        })
    for record in stronger["records"]:
        records.append({
            "sequence": record["sequence"],
            "platform": record["platform"],
            "regime": record["regime"],
            "start_sec": record["start_sec"],
            "duration_sec": record["duration_sec"],
            "selection_window": record["selection_window"],
            "selection_source": "report/dynamic_init_fast_selection.json",
        })
    return records


def state_gate(sequence: str, platform: str) -> dict:
    root = ROOT / "results" / sequence
    frames = {
        method: pd.read_csv(root / method / "state_log.csv").dropna()
        for method in METHODS
    }
    reference_time = frames["A"]["t"].to_numpy()
    gt_length = gt_path_length(
        ROOT / base.DATASETS[platform]["gt"],
        float(reference_time[0]), float(reference_time[-1]),
    )
    arc_ratios = {}
    finite = {}
    for method, frame in frames.items():
        position = frame[["px", "py", "pz"]].to_numpy()
        estimate_length = float(np.linalg.norm(
            np.diff(position, axis=0), axis=1).sum())
        arc_ratios[method] = estimate_length / gt_length
        finite[method] = bool(np.isfinite(
            frame.select_dtypes(include=[np.number]).to_numpy()).all())
    accuracy_admitted = {
        method: finite[method] and 0.6 <= arc_ratios[method] <= 1.6
        for method in METHODS
    }
    return {
        "frames": {method: int(len(frame)) for method, frame in frames.items()},
        "timestamps_all_equal": all(np.array_equal(
            frame["t"].to_numpy(), reference_time)
            for frame in frames.values()),
        "gravity_max_component_motion": {
            method: float(np.max(np.abs(
                frame[["gx", "gy", "gz"]].to_numpy()
                - frame[["gx", "gy", "gz"]].iloc[0].to_numpy())))
            for method, frame in frames.items()
        },
        "ba_max_component_motion": {
            method: float(np.max(np.abs(
                frame[["bax", "bay", "baz"]].to_numpy()
                - frame[["bax", "bay", "baz"]].iloc[0].to_numpy())))
            for method, frame in frames.items()
        },
        "binary_sha1": {
            method: base.meta(root / method).get("fastlio_binary_sha1")
            for method in METHODS
        },
        "gt_length_m": gt_length,
        "estimate_to_gt_arc_ratio": arc_ratios,
        "finite_state": finite,
        "accuracy_admitted": accuracy_admitted,
        "outcome": {
            method: ("accuracy_admitted" if accuracy_admitted[method]
                     else "complete_estimator_divergence")
            for method in METHODS
        },
    }


def main() -> int:
    records = []
    for source in source_records():
        sequence = source["sequence"]
        platform = source["platform"]
        result_dir = ROOT / "results" / sequence
        metrics = json.loads(
            (result_dir / "analysis" / "metrics.json").read_text())["runs"]
        missing = set(METHODS) - set(metrics)
        if missing:
            raise RuntimeError(f"{sequence}: missing metrics for {sorted(missing)}")

        metric_values = {
            metric: {method: float(metrics[method][metric]) for method in METHODS}
            for metric in METRICS
        }
        contrasts = {}
        for metric, values in metric_values.items():
            contrasts[metric] = {
                "fixg_vs_online": effect(values["RED21"], values["A"]),
                "fixba_vs_online": effect(values["RED20"], values["A"]),
                "fixgba_vs_online": effect(values["RED18"], values["A"]),
                "fixg_given_fixed_ba": effect(values["RED18"], values["RED20"]),
                "fixba_given_fixed_g": effect(values["RED18"], values["RED21"]),
                "factorial_interaction": log_interaction(values),
            }

        gates = state_gate(sequence, platform)
        time_windows = {
            method: base.aligned_window_metrics(sequence, platform, method)
            for method in METHODS
        }
        records.append({
            **source,
            "gates": gates,
            "metrics": {
                method: {metric: float(metrics[method][metric]) for metric in METRICS}
                for method in METHODS
            },
            "contrasts": contrasts,
            "time_windows": time_windows,
        })

    aggregate = {}
    contrast_methods = {
        "fixg_vs_online": ("A", "RED21"),
        "fixba_vs_online": ("A", "RED20"),
        "fixgba_vs_online": ("A", "RED18"),
        "factorial_interaction": METHODS,
    }
    for regime in ("quiet", "dynamic", "stronger_natural_motion"):
        subset = [record for record in records if record["regime"] == regime]
        aggregate[regime] = {
            "phases": len(subset),
            "method_failure_counts": {
                method: int(sum(
                    not record["gates"]["accuracy_admitted"][method]
                    for record in subset
                ))
                for method in METHODS
            },
            "metrics": {},
        }
        for metric in METRICS:
            aggregate[regime]["metrics"][metric] = {}
            for contrast in (
                "fixg_vs_online",
                "fixba_vs_online",
                "fixgba_vs_online",
                "factorial_interaction",
            ):
                admitted_records = [
                    record for record in subset
                    if all(record["gates"]["accuracy_admitted"][method]
                           for method in contrast_methods[contrast])
                ]
                values = [
                    record["contrasts"][metric][contrast]["relative_pct"]
                    for record in admitted_records
                ]
                summary = {
                    "admitted_phases": len(values),
                    "failure_phases": len(subset) - len(values),
                    "positive_phases": int(sum(value > 0.4 for value in values)),
                    "negative_phases": int(sum(value < -0.4 for value in values)),
                    "indistinguishable_phases": int(sum(abs(value) <= 0.4 for value in values)),
                }
                if values:
                    summary.update({
                        "median_pct": float(np.median(values)),
                        "range_pct": [float(min(values)), float(max(values))],
                    })
                aggregate[regime]["metrics"][metric][contrast] = summary

    both_metric_wins = {method: 0 for method in METHODS}
    for record in records:
        for method in METHODS:
            if (record["gates"]["accuracy_admitted"]["A"]
                    and record["gates"]["accuracy_admitted"][method]
                    and all(
                record["metrics"][method][metric]
                < record["metrics"]["A"][metric] * 0.996
                for metric in METRICS
            )):
                both_metric_wins[method] += 1

    report = {
        "schema": 1,
        "status": "completed_structural_gates_with_retained_estimator_failures",
        "design": {
            "estimators": {method: LABELS[method] for method in METHODS},
            "unit": "one outcome-locked 60 s rosbag start phase",
            "phase_count": len(records),
            "run_count": len(records) * len(METHODS),
            "new_runs": len(records) * 2,
            "noise_floor_pct": 0.4,
            "inference": "phase-level descriptive factorial; no cross-phase pooled population test",
        },
        "records": records,
        "aggregate": aggregate,
        "both_metric_wins_relative_to_online": both_metric_wins,
        "interpretation_boundary": [
            "A versus RED21 isolates gravity while keeping accelerometer bias online.",
            "A versus RED18 is the operational fully-online versus fully-fixed contrast but does not isolate a state.",
            "The four cells expose gravity-by-bias interaction under the shared acceleration-mean initializer.",
            "Complete finite arc-ratio failures are retained as estimator failures and excluded from ordinary percentage summaries.",
            "The experiment does not compare a motion-aware initializer for the fixed-state designs.",
        ],
    }
    output = ROOT / "report" / "dynamic_init_factorial.json"
    output.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")

    lines = [
        "# Dynamic-start true-manifold 2x2",
        "",
        "Effects are relative to Online; positive means the reduced method is worse.",
        "",
        "| Platform | Regime | Start [s] | FixG z/ATE [%] | FixBa z/ATE [%] | FixG+Ba z/ATE [%] | interaction z/ATE [%] |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for record in records:
        contrasts = record["contrasts"]
        def pair(name, candidate):
            admitted = record["gates"]["accuracy_admitted"]
            if not (admitted["A"] and admitted[candidate]):
                metrics = record["metrics"][candidate]
                return f"FAIL ({metrics['rmse_z_m']:.2f}/{metrics['ate_rmse_m']:.2f} m)"
            return (f"{contrasts['rmse_z_m'][name]['relative_pct']:+.2f}/"
                    f"{contrasts['ate_rmse_m'][name]['relative_pct']:+.2f}")
        if all(record["gates"]["accuracy_admitted"].values()):
            interaction = (f"{contrasts['rmse_z_m']['factorial_interaction']['relative_pct']:+.2f}/"
                           f"{contrasts['ate_rmse_m']['factorial_interaction']['relative_pct']:+.2f}")
        else:
            interaction = "n/a (failure)"
        lines.append(
            f"| {record['platform']} | {record['regime']} | {record['start_sec']:.3f} | "
            f"{pair('fixg_vs_online', 'RED21')} | {pair('fixba_vs_online', 'RED20')} | "
            f"{pair('fixgba_vs_online', 'RED18')} | {interaction} |"
        )
    lines += [
        "",
        "This is a phase-level stress test under one shared static-mean initializer, not a comparison with an optimal motion-aware initializer.",
    ]
    (ROOT / "report" / "DYNAMIC_INIT_FACTORIAL.md").write_text(
        "\n".join(lines) + "\n")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
