#!/usr/bin/env python3
"""Collect stronger-motion Online/FixG initialization pairs."""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import collect_dynamic_init as base  # noqa: E402
import collect_metrics as registry  # noqa: E402


def main() -> int:
    selection = json.loads(
        (ROOT / "report" / "dynamic_init_fast_selection.json").read_text())
    if selection.get("status") != "selection_locked_before_slam_outcomes":
        raise RuntimeError("stronger-motion phase selection is not locked")

    sensors = {platform: base.load_sensor_data(platform) for platform in base.DATASETS}
    records = []
    for selected in selection["records"]:
        sequence = selected["sequence"]
        platform = selected["platform"]
        result_dir = ROOT / "results" / sequence
        metrics = json.loads(
            (result_dir / "analysis" / "metrics.json").read_text())["runs"]
        frames = {
            run: pd.read_csv(result_dir / run / "state_log.csv").dropna()
            for run in ("A", "RED21")
        }
        online_g = frames["A"][["gx", "gy", "gz"]].to_numpy()
        fixed_g = frames["RED21"][["gx", "gy", "gz"]].to_numpy()
        g0_online = online_g[0] / np.linalg.norm(online_g[0])
        g0_fixed = fixed_g[0] / np.linalg.norm(fixed_g[0])
        initial_pair_angle = float(np.degrees(np.arccos(
            np.clip(g0_online @ g0_fixed, -1.0, 1.0))))
        fixed_drift = float(np.max(np.abs(fixed_g - fixed_g[0])))
        online_drift = float(np.max(np.abs(online_g - online_g[0])))
        timestamp_equal = bool(np.array_equal(
            frames["A"]["t"].to_numpy(), frames["RED21"]["t"].to_numpy()))
        if len(frames["A"]) != len(frames["RED21"]) or not timestamp_equal:
            raise RuntimeError(f"{sequence}: paired frame/timestamp gate failed")
        if initial_pair_angle >= 0.1 or fixed_drift > 1e-12 or online_drift <= 1e-12:
            raise RuntimeError(f"{sequence}: gravity-state gate failed")
        gt_cfg = registry.SEQS[sequence]
        gt_path = ROOT / gt_cfg["gt"]
        gt = registry.gt_extent(
            gt_path, registry.estimate_time_range(result_dir))
        gt_usable, est_over_gt = registry.gt_sanity(
            result_dir, gt["path_len_m"])
        attitude_usable = max(
            metrics["A"]["rmse_roll_deg"],
            metrics["A"]["rmse_pitch_deg"],
        ) < 20.0
        if not gt_usable or not attitude_usable:
            raise RuntimeError(f"{sequence}: GT gate failed")
        window_metrics = {
            run: base.aligned_window_metrics(sequence, platform, run)
            for run in ("A", "RED21")
        }
        window_effects = {
            label: {
                metric: base.effect(
                    window_metrics["RED21"][label][metric],
                    window_metrics["A"][label][metric],
                )
                for metric in ("rmse_z_m", "ate_rmse_m")
            }
            for label in window_metrics["A"]
        }
        records.append({
            "sequence": sequence,
            "platform": platform,
            "regime": "stronger_natural_motion",
            "start_sec": selected["start_sec"],
            "duration_sec": selected["duration_sec"],
            "selection_window": base.selection_window(
                platform, selected["start_sec"], sensors[platform]),
            "gates": {
                "frames": {run: int(len(frame)) for run, frame in frames.items()},
                "timestamp_equal": timestamp_equal,
                "initial_gravity_pair_angle_deg": initial_pair_angle,
                "fixed_gravity_max_component_drift": fixed_drift,
                "online_gravity_max_component_drift": online_drift,
                "binary_sha1": {
                    run: base.meta(result_dir / run).get("fastlio_binary_sha1")
                    for run in ("A", "RED21")
                },
                "gt": {
                    **gt,
                    "est_over_gt_ratio": est_over_gt,
                    "usable": gt_usable,
                    "attitude_usable": attitude_usable,
                },
            },
            "metrics": {run: metrics[run] for run in ("A", "RED21")},
            "effects_fixg_minus_online": {
                "rmse_z": base.effect(
                    metrics["RED21"]["rmse_z_m"], metrics["A"]["rmse_z_m"]),
                "ate": base.effect(
                    metrics["RED21"]["ate_rmse_m"], metrics["A"]["ate_rmse_m"]),
            },
            "time_windows": window_metrics,
            "time_window_effects_fixg_minus_online": window_effects,
        })

    aggregate = {}
    for platform in base.DATASETS:
        platform_records = [
            record for record in records if record["platform"] == platform]
        aggregate[platform] = {}
        for metric in ("rmse_z", "ate"):
            values = [
                record["effects_fixg_minus_online"][metric]["relative_pct"]
                for record in platform_records
            ]
            aggregate[platform][f"{metric}_range_pct"] = [
                float(min(values)), float(max(values))]
            aggregate[platform][f"{metric}_median_pct"] = float(np.median(values))
            aggregate[platform][f"{metric}_online_better_phases"] = int(
                sum(v > 0.4 for v in values))

    report = {
        "schema": 1,
        "status": "completed_structural_and_gt_gates_pass",
        "selection_source": "report/dynamic_init_fast_selection.json",
        "design": {
            "estimators": {
                "A": "23D Online g + online ba",
                "RED21": "21D FixG + online ba",
            },
            "unit": "paired 60 s suffix at one outcome-blind stronger-motion start",
            "pairs": len(records),
            "noise_floor_pct": 0.4,
            "failure_definition": "incomplete/non-finite/reset output or a failed structural gate; large finite error remains an accuracy outcome",
        },
        "records": records,
        "aggregate": aggregate,
    }
    output = ROOT / "report" / "dynamic_init_fast.json"
    output.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")

    lines = [
        "# Stronger-motion dynamic initialization",
        "",
        "All effects are FixG minus Online; positive means FixG is worse.",
        "",
        "| Platform | Start [s] | init descriptor [deg] | gyro [rad/s] | RMSE_z Online/FixG [m] | ATE Online/FixG [m] | Delta RMSE_z [%] | Delta ATE [%] | Online g motion [deg] |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for record in records:
        window = record["selection_window"]
        lines.append(
            f"| {record['platform']} | {record['start_sec']:.3f} | "
            f"{window['apparent_gravity_angle_deg']:.2f} | "
            f"{window['mean_gyro_norm_radps']:.3f} | "
            f"{record['metrics']['A']['rmse_z_m']:.3f}/{record['metrics']['RED21']['rmse_z_m']:.3f} | "
            f"{record['metrics']['A']['ate_rmse_m']:.3f}/{record['metrics']['RED21']['ate_rmse_m']:.3f} | "
            f"{record['effects_fixg_minus_online']['rmse_z']['relative_pct']:+.2f} | "
            f"{record['effects_fixg_minus_online']['ate']['relative_pct']:+.2f} | "
            f"{record['metrics']['A']['grav_angle_max_deg']:.2f} |"
        )
    lines += [
        "",
        "The initialization descriptor is GT-referenced and outcome-blind; it is not an exact reconstruction of the estimator's internal IMU buffer.",
    ]
    (ROOT / "report" / "DYNAMIC_INIT_FAST.md").write_text("\n".join(lines) + "\n")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
