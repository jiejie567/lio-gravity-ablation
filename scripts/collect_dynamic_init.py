#!/usr/bin/env python3
"""Collect the paired quasi-static/dynamic-start initialization experiment."""

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from rosbags.highlevel import AnyReader
from scipy.spatial.transform import Rotation, Slerp


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import analyze as trajectory_analysis  # noqa: E402


E2B = {
    "vehicle": np.array([
        0.054216, -0.001058, -0.028667,
        0.999935, 0.003587, -0.010854,
        0.003478, -0.999943, -0.010092,
        -0.010890, 0.010054, -0.999890,
    ]),
    "handheld": np.array([
        0.042216, -0.019535, -0.026406,
        0.999914, -0.011356, -0.006635,
        -0.011166, -0.999545, 0.028009,
        -0.006950, -0.027932, -0.999586,
    ]),
}

DATASETS = {
    "vehicle": {
        "bag": "data/mcd/ntu_day_10_os1/os1.bag",
        "gt": "data/mcd/ntu_day_10/gt/pose_inW.csv",
    },
    "handheld": {
        "bag": "data/mcd/tuhh_day_04_os1/os1.bag",
        "gt": "data/mcd/tuhh_day_04/gt/pose_inW.csv",
    },
}

PHASES = [
    ("vehicle", "quiet", 14.683, "ntu_day_10_quietinit_s14p683"),
    ("vehicle", "dynamic", 66.476, "ntu_day_10_dyninit_s66p476"),
    ("vehicle", "dynamic", 78.568, "ntu_day_10_dyninit_s78p568"),
    ("vehicle", "dynamic", 106.868, "ntu_day_10_dyninit_s106p868"),
    ("handheld", "quiet", 6.679, "tuhh_day_04_quietinit_s6p679"),
    ("handheld", "dynamic", 38.271, "tuhh_day_04_dyninit_s38p271"),
    ("handheld", "dynamic", 56.170, "tuhh_day_04_dyninit_s56p170"),
    ("handheld", "dynamic", 98.779, "tuhh_day_04_dyninit_s98p779"),
]

TIME_WINDOWS = ((0.0, 10.0), (10.0, 30.0), (30.0, 60.0))


def effect(fixed: float, online: float) -> dict:
    return {
        "absolute_m": fixed - online,
        "relative_pct": (fixed / online - 1.0) * 100.0,
    }


def meta(run_dir: Path) -> dict[str, str]:
    out = {}
    for line in (run_dir / "run_meta.txt").read_text().splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            out[key.strip()] = value.strip()
    return out


def load_sensor_data(platform: str) -> dict:
    dataset = DATASETS[platform]
    bag = ROOT / dataset["bag"]
    with AnyReader([bag]) as reader:
        bag_start = reader.start_time / 1e9
        wanted = {
            connection.topic: connection
            for connection in reader.connections
            if connection.topic in ("/os_cloud_node/imu", "/os_cloud_node/points")
        }
        imu_t, acceleration, gyro, lidar_t = [], [], [], []
        for connection, timestamp, raw in reader.messages(connections=list(wanted.values())):
            time_s = timestamp / 1e9
            if connection.topic.endswith("/imu"):
                message = reader.deserialize(raw, connection.msgtype)
                imu_t.append(time_s)
                acceleration.append([
                    message.linear_acceleration.x,
                    message.linear_acceleration.y,
                    message.linear_acceleration.z,
                ])
                gyro.append([
                    message.angular_velocity.x,
                    message.angular_velocity.y,
                    message.angular_velocity.z,
                ])
            else:
                lidar_t.append(time_s)

    ground_truth = pd.read_csv(ROOT / dataset["gt"])
    return {
        "bag_start": bag_start,
        "imu_t": np.asarray(imu_t),
        "acceleration": np.asarray(acceleration),
        "gyro": np.asarray(gyro),
        "lidar_t": np.asarray(lidar_t),
        "gt_t": ground_truth["t"].to_numpy(),
        "gt_rotation": Rotation.from_quat(
            ground_truth[["qx", "qy", "qz", "qw"]].to_numpy()),
    }


def selection_window(platform: str, start_sec: float, sensor: dict) -> dict:
    """Describe the 150 ms window used to select a start phase.

    This is an auditable motion indicator, not a claim that it reproduces the
    estimator's internal buffer sample-for-sample.
    """
    target = sensor["bag_start"] + start_sec
    lidar_index = int(np.searchsorted(sensor["lidar_t"], target))
    lidar_time = float(sensor["lidar_t"][lidar_index])
    mask = ((sensor["imu_t"] >= lidar_time - 0.02)
            & (sensor["imu_t"] <= lidar_time + 0.13))
    acceleration = sensor["acceleration"][mask]
    gyro = sensor["gyro"][mask]
    mean_acceleration = acceleration.mean(axis=0)
    mean_gyro = gyro.mean(axis=0)

    slerp = Slerp(sensor["gt_t"], sensor["gt_rotation"])
    body_in_world = slerp([lidar_time]).as_matrix()[0]
    imu_to_body = E2B[platform][3:].reshape(3, 3)
    imu_in_world = body_in_world @ imu_to_body.T
    expected_up_in_imu = imu_in_world.T @ np.array([0.0, 0.0, 1.0])
    observed = mean_acceleration / np.linalg.norm(mean_acceleration)
    apparent_angle = float(np.degrees(np.arccos(
        np.clip(observed @ expected_up_in_imu, -1.0, 1.0))))
    return {
        "definition": "IMU samples from 20 ms before to 130 ms after the first selected LiDAR timestamp",
        "is_exact_estimator_buffer": False,
        "first_selected_lidar_time": lidar_time,
        "imu_samples": int(mask.sum()),
        "mean_acceleration_norm_mps2": float(np.linalg.norm(mean_acceleration)),
        "acceleration_std_norm_mps2": float(np.linalg.norm(acceleration.std(axis=0))),
        "mean_gyro_norm_radps": float(np.linalg.norm(mean_gyro)),
        "apparent_gravity_angle_deg": apparent_angle,
    }


def aligned_window_metrics(sequence: str, platform: str, run: str) -> dict:
    dataset = DATASETS[platform]
    ground_truth = trajectory_analysis.load_gt_tum(ROOT / dataset["gt"])
    frame = pd.read_csv(ROOT / "results" / sequence / run / "state_log.csv").dropna()
    time = frame["t"].to_numpy()
    mask, position_gt, _ = trajectory_analysis.interp_gt(ground_truth, time)
    position = frame[["px", "py", "pz"]].to_numpy()[mask]
    attitude = Rotation.from_quat(
        frame[["qx", "qy", "qz", "qw"]].to_numpy()[mask])
    transform = E2B[platform]
    position += attitude.apply(transform[:3])
    time = time[mask]

    arc = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(position_gt, axis=0), axis=1))]
    align_count = max(
        10,
        int(np.searchsorted(time, time[0] + 10.0)),
        int(np.searchsorted(arc, 30.0)),
    )
    align_count = min(align_count, len(time) - 1)
    rotation, translation = trajectory_analysis.umeyama_rigid(
        position[:align_count], position_gt[:align_count])
    aligned = position @ rotation.T + translation
    z_error = aligned[:, 2] - position_gt[:, 2]
    error_3d = np.linalg.norm(aligned - position_gt, axis=1)
    elapsed = time - time[0]

    out = {}
    for lower, upper in TIME_WINDOWS:
        selected = (elapsed >= lower) & (elapsed < upper)
        out[f"{int(lower)}_{int(upper)}s"] = {
            "rmse_z_m": float(np.sqrt(np.mean(z_error[selected] ** 2))),
            "ate_rmse_m": float(np.sqrt(np.mean(error_3d[selected] ** 2))),
            "frames": int(selected.sum()),
        }
    return out


def main() -> int:
    sensor_cache = {platform: load_sensor_data(platform) for platform in DATASETS}
    records = []
    for platform, regime, start_sec, sequence in PHASES:
        result_dir = ROOT / "results" / sequence
        metrics_path = result_dir / "analysis" / "metrics.json"
        metrics = json.loads(metrics_path.read_text())["runs"]
        frames = {
            run: pd.read_csv(result_dir / run / "state_log.csv").dropna()
            for run in ("A", "RED21")
        }
        timestamp_equal = np.array_equal(
            frames["A"]["t"].to_numpy(), frames["RED21"]["t"].to_numpy())
        g_online = frames["A"][["gx", "gy", "gz"]].to_numpy()
        g_fixed = frames["RED21"][["gx", "gy", "gz"]].to_numpy()
        g0a = g_online[0] / np.linalg.norm(g_online[0])
        g0f = g_fixed[0] / np.linalg.norm(g_fixed[0])

        window_metrics = {
            run: aligned_window_metrics(sequence, platform, run)
            for run in ("A", "RED21")
        }
        window_effects = {}
        for label in window_metrics["A"]:
            window_effects[label] = {
                metric: effect(
                    window_metrics["RED21"][label][metric],
                    window_metrics["A"][label][metric],
                )
                for metric in ("rmse_z_m", "ate_rmse_m")
            }

        run_meta = {run: meta(result_dir / run) for run in ("A", "RED21")}
        records.append({
            "sequence": sequence,
            "platform": platform,
            "regime": regime,
            "start_sec": start_sec,
            "duration_sec": 60.0,
            "selection_window": selection_window(platform, start_sec, sensor_cache[platform]),
            "gates": {
                "frames": {run: int(len(frame)) for run, frame in frames.items()},
                "timestamp_equal": bool(timestamp_equal),
                "initial_gravity_pair_angle_deg": float(np.degrees(np.arccos(
                    np.clip(g0a @ g0f, -1.0, 1.0)))),
                "fixed_gravity_max_component_drift": float(
                    np.max(np.abs(g_fixed - g_fixed[0]))),
                "online_gravity_max_component_drift": float(
                    np.max(np.abs(g_online - g_online[0]))),
                "binary_sha1": {
                    run: run_meta[run].get("fastlio_binary_sha1")
                    for run in ("A", "RED21")
                },
            },
            "metrics": metrics,
            "effects_fixg_minus_online": {
                "rmse_z": effect(metrics["RED21"]["rmse_z_m"], metrics["A"]["rmse_z_m"]),
                "ate": effect(metrics["RED21"]["ate_rmse_m"], metrics["A"]["ate_rmse_m"]),
            },
            "time_windows": window_metrics,
            "time_window_effects_fixg_minus_online": window_effects,
        })

    aggregate = {}
    for platform in DATASETS:
        platform_records = [record for record in records if record["platform"] == platform]
        quiet = next(record for record in platform_records if record["regime"] == "quiet")
        dynamic = [record for record in platform_records if record["regime"] == "dynamic"]
        aggregate[platform] = {
            "quiet_effect_pct": {
                metric: quiet["effects_fixg_minus_online"][metric]["relative_pct"]
                for metric in ("rmse_z", "ate")
            },
            "dynamic_effect_pct": {
                metric: [
                    record["effects_fixg_minus_online"][metric]["relative_pct"]
                    for record in dynamic
                ]
                for metric in ("rmse_z", "ate")
            },
        }
        for metric in ("rmse_z", "ate"):
            values = aggregate[platform]["dynamic_effect_pct"][metric]
            aggregate[platform][f"dynamic_{metric}_median_pct"] = float(np.median(values))
            aggregate[platform][f"dynamic_{metric}_range_pct"] = [float(min(values)), float(max(values))]
            aggregate[platform][f"dynamic_{metric}_positive_phases"] = int(sum(v > 0 for v in values))

    report = {
        "schema": 1,
        "generated_from": [
            "results/*_quietinit_*/{A,RED21}/state_log.csv",
            "results/*_dyninit_*/{A,RED21}/state_log.csv",
            "results/*_*init_*/analysis/metrics.json",
        ],
        "design": {
            "estimators": {"A": "23D Online g + online ba", "RED21": "21D FixG + online ba"},
            "unit": "paired 60 s suffix at one rosbag start phase",
            "trajectories": 2,
            "quiet_phases_per_trajectory": 1,
            "dynamic_phases_per_trajectory": 3,
            "noise_floor_pct": 0.4,
        },
        "records": records,
        "aggregate": aggregate,
        "interpretation": [
            "Quasi-static starts keep Online and FixG close on both trajectories.",
            "Dynamic starts increase sensitivity to the gravity-state choice, but do not make Online universally superior.",
            "All three handheld dynamic phases favor Online in ATE; vehicle dynamic phases have mixed signs in both metrics.",
            "The intervention tests recovery from the shared static-mean initializer, not an optimal motion-aware initializer.",
        ],
    }
    output = ROOT / "report" / "dynamic_init.json"
    output.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")

    lines = [
        "# Dynamic-start initialization experiment",
        "",
        "All values are FixG relative to Online; positive means FixG is worse.",
        "",
        "| Platform | Regime | Start [s] | apparent init angle [deg] | RMSE_z [%] | ATE [%] | Online g motion [deg] |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for record in records:
        lines.append(
            f"| {record['platform']} | {record['regime']} | {record['start_sec']:.3f} | "
            f"{record['selection_window']['apparent_gravity_angle_deg']:.2f} | "
            f"{record['effects_fixg_minus_online']['rmse_z']['relative_pct']:+.2f} | "
            f"{record['effects_fixg_minus_online']['ate']['relative_pct']:+.2f} | "
            f"{record['metrics']['A']['grav_angle_max_deg']:.2f} |"
        )
    lines += [
        "",
        "The selection angle is a GT-referenced descriptor of the 150 ms phase-selection window, not an exact reconstruction of the estimator's internal IMU buffer.",
    ]
    (ROOT / "report" / "DYNAMIC_INIT.md").write_text("\n".join(lines) + "\n")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
