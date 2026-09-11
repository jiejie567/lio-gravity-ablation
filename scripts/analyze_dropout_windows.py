#!/usr/bin/env python3
"""Reconstruct IMU-only dropout windows and measure first-scan recovery."""

from __future__ import annotations

import csv
import json
import math
import statistics
from pathlib import Path

import numpy as np
from rosbags.rosbag1 import Reader
from rosbags.typesys import Stores, get_typestore
from scipy.spatial.transform import Rotation

from collect_liosam_direction import load_gt, rigid_alignment


ROOT = Path(__file__).resolve().parent.parent
TS = get_typestore(Stores.ROS1_NOETIC)
POS = tuple(f"field.pose.pose.position.{axis}" for axis in "xyz")
QUAT = tuple(f"field.pose.pose.orientation.{axis}" for axis in "xyzw")


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def stamp(message: object) -> float:
    value = message.header.stamp
    return float(value.sec) + float(value.nanosec) * 1e-9


def first_topic_stamp(path: Path, topic: str) -> float:
    with Reader(path) as reader:
        for connection, timestamp, _ in reader.messages():
            if connection.topic == topic:
                return timestamp * 1e-9
    raise RuntimeError(f"{path}: missing topic {topic}")


def load_imu(path: Path, topic: str, extrinsic_rotation: np.ndarray) -> dict[str, np.ndarray]:
    time: list[float] = []
    acceleration: list[np.ndarray] = []
    angular_velocity: list[np.ndarray] = []
    with Reader(path) as reader:
        for connection, _, raw in reader.messages():
            if connection.topic != topic:
                continue
            message = TS.deserialize_ros1(raw, connection.msgtype)
            time.append(stamp(message))
            acceleration.append(
                extrinsic_rotation
                @ np.array(
                    [
                        message.linear_acceleration.x,
                        message.linear_acceleration.y,
                        message.linear_acceleration.z,
                    ]
                )
            )
            angular_velocity.append(
                extrinsic_rotation
                @ np.array(
                    [
                        message.angular_velocity.x,
                        message.angular_velocity.y,
                        message.angular_velocity.z,
                    ]
                )
            )
    return {
        "time": np.asarray(time),
        "acceleration": np.asarray(acceleration),
        "angular_velocity": np.asarray(angular_velocity),
    }


def run_series(
    run: Path,
    dataset: str,
    gt_time: np.ndarray,
    gt_position: np.ndarray,
    body_translation: np.ndarray | None,
) -> dict[str, object]:
    state = rows(run / "state_log.csv")
    odometry = rows(run / "odometry.csv")
    state_time = np.asarray([float(row["timestamp"]) for row in state])
    odom_time = np.asarray([float(row["%time"]) * 1e-9 for row in odometry])
    right = np.clip(np.searchsorted(odom_time, state_time), 0, len(odom_time) - 1)
    left = np.clip(right - 1, 0, len(odom_time) - 1)
    indices = np.where(
        np.abs(odom_time[right] - state_time)
        < np.abs(odom_time[left] - state_time),
        right,
        left,
    )
    if np.max(np.abs(odom_time[indices] - state_time)) > 2e-6:
        raise RuntimeError(f"{run}: state/odometry timestamp association failed")

    position = np.asarray(
        [[float(odometry[index][field]) for field in POS] for index in indices]
    )
    quaternion = np.asarray(
        [[float(odometry[index][field]) for field in QUAT] for index in indices]
    )
    orientation = Rotation.from_quat(quaternion)
    if body_translation is not None:
        position = position + orientation.apply(body_translation)

    valid = (state_time >= gt_time[0]) & (state_time <= gt_time[-1])
    state_time = state_time[valid]
    position = position[valid]
    quaternion = quaternion[valid]
    state = [row for row, keep in zip(state, valid) if keep]
    truth = np.column_stack(
        [np.interp(state_time, gt_time, gt_position[:, axis]) for axis in range(3)]
    )
    align_count = max(10, int(np.searchsorted(state_time, state_time[0] + 10.0)))
    align_rotation, align_translation = rigid_alignment(
        position[:align_count], truth[:align_count]
    )
    aligned = position @ align_rotation.T + align_translation
    error = aligned - truth
    return {
        "time": state_time,
        "state": state,
        "quaternion": quaternion,
        "error": error,
        "align_rotation": align_rotation,
        "align_translation": align_translation,
    }


def propagate(
    state: dict[str, str],
    quaternion: np.ndarray,
    imu: dict[str, np.ndarray],
    end_time: float,
    lidar_from_imu_translation: np.ndarray | None,
) -> np.ndarray:
    start_time = float(state["timestamp"])
    position = np.array([float(state[field]) for field in ("px", "py", "pz")])
    velocity = np.array([float(state[field]) for field in ("vx", "vy", "vz")])
    accelerometer_bias = np.array(
        [float(state[field]) for field in ("bax", "bay", "baz")]
    )
    gyroscope_bias = np.array(
        [float(state[field]) for field in ("bgx", "bgy", "bgz")]
    )
    gravity = np.array([float(state[field]) for field in ("gx", "gy", "gz")])
    orientation = Rotation.from_quat(quaternion)

    imu_time = imu["time"]
    start = max(0, int(np.searchsorted(imu_time, start_time, side="right") - 1))
    stop = int(np.searchsorted(imu_time, end_time, side="right"))
    previous = start_time
    last_acceleration = imu["acceleration"][start]
    last_angular_velocity = imu["angular_velocity"][start]
    for index in range(start + 1, stop):
        current = min(float(imu_time[index]), end_time)
        delta = current - previous
        if delta <= 0.0:
            continue
        angular_velocity = 0.5 * (
            last_angular_velocity + imu["angular_velocity"][index]
        ) - gyroscope_bias
        half_rotation = orientation * Rotation.from_rotvec(0.5 * angular_velocity * delta)
        specific_force = 0.5 * (
            last_acceleration + imu["acceleration"][index]
        ) - accelerometer_bias
        world_acceleration = half_rotation.apply(specific_force) + gravity
        position = position + velocity * delta + 0.5 * world_acceleration * delta * delta
        velocity = velocity + world_acceleration * delta
        orientation = orientation * Rotation.from_rotvec(angular_velocity * delta)
        previous = current
        last_acceleration = imu["acceleration"][index]
        last_angular_velocity = imu["angular_velocity"][index]

    if previous < end_time:
        delta = end_time - previous
        angular_velocity = last_angular_velocity - gyroscope_bias
        half_rotation = orientation * Rotation.from_rotvec(0.5 * angular_velocity * delta)
        world_acceleration = (
            half_rotation.apply(last_acceleration - accelerometer_bias) + gravity
        )
        position = position + velocity * delta + 0.5 * world_acceleration * delta * delta
        orientation = orientation * Rotation.from_rotvec(angular_velocity * delta)

    if lidar_from_imu_translation is not None:
        position = position - orientation.apply(lidar_from_imu_translation)
    return position


def median_range(values: list[float]) -> dict[str, object]:
    return {
        "median": statistics.median(values),
        "range": [min(values), max(values)],
    }


def analyze_run(
    run: Path,
    dataset: str,
    gt_path: Path,
    imu: dict[str, np.ndarray],
    lidar_t0: float,
    gap_s: float,
    body_translation: np.ndarray | None,
    lidar_from_imu_translation: np.ndarray | None,
) -> dict[str, object]:
    gt_time, gt_position = load_gt(gt_path, dataset)
    series = run_series(run, dataset, gt_time, gt_position, body_translation)
    time = series["time"]
    error = series["error"]
    windows: list[dict[str, object]] = []
    period = 20.0
    first_cycle = math.floor((time[0] - lidar_t0) / period)
    last_cycle = math.ceil((time[-1] - lidar_t0) / period)
    for cycle in range(first_cycle, last_cycle + 1):
        gap_start = lidar_t0 + cycle * period + (period - gap_s)
        gap_end = lidar_t0 + (cycle + 1) * period
        pre_candidates = np.flatnonzero(time <= gap_start)
        return_candidates = np.flatnonzero(time >= gap_end)
        if not len(pre_candidates) or not len(return_candidates):
            continue
        pre = int(pre_candidates[-1])
        returned = int(return_candidates[0])
        if returned <= pre or time[returned] - time[pre] < 0.8 * gap_s:
            continue

        predicted = propagate(
            series["state"][pre],
            series["quaternion"][pre],
            imu,
            float(time[returned]),
            lidar_from_imu_translation,
        )
        predicted_aligned = (
            series["align_rotation"] @ predicted + series["align_translation"]
        )
        truth_return = np.array(
            [
                np.interp(time[returned], gt_time, gt_position[:, axis])
                for axis in range(3)
            ]
        )
        predicted_error = predicted_aligned - truth_return
        pre_ate = float(np.linalg.norm(error[pre]))
        pre_z = float(abs(error[pre, 2]))
        predicted_ate = float(np.linalg.norm(predicted_error))
        predicted_z = float(abs(predicted_error[2]))
        return_ate = float(np.linalg.norm(error[returned]))
        return_z = float(abs(error[returned, 2]))
        follow = np.flatnonzero(
            (time >= time[returned]) & (time <= time[returned] + 2.0)
        )
        best_ate = float(np.min(np.linalg.norm(error[follow], axis=1)))
        best_z = float(np.min(np.abs(error[follow, 2])))
        ate_threshold = max(0.05, 1.25 * pre_ate)
        z_threshold = max(0.05, 1.25 * pre_z)
        windows.append(
            {
                "cycle": cycle,
                "gap_start_s": gap_start,
                "gap_end_s": gap_end,
                "last_correction_s": float(time[pre]),
                "first_return_s": float(time[returned]),
                "coast_duration_s": float(time[returned] - time[pre]),
                "pre_error": {"z_m": pre_z, "ate_m": pre_ate},
                "imu_reconstruction_at_return": {
                    "z_m": predicted_z,
                    "ate_m": predicted_ate,
                    "z_growth_m": predicted_z - pre_z,
                    "ate_growth_m": predicted_ate - pre_ate,
                },
                "first_return_error": {"z_m": return_z, "ate_m": return_ate},
                "best_error_within_2s": {"z_m": best_z, "ate_m": best_ate},
                "contracted_at_first_return": {
                    "z": return_z < predicted_z,
                    "ate": return_ate < predicted_ate,
                },
                "recovered_within_2s": {
                    "z": best_z <= z_threshold,
                    "ate": best_ate <= ate_threshold,
                    "both": best_z <= z_threshold and best_ate <= ate_threshold,
                },
                "recovery_threshold": {"z_m": z_threshold, "ate_m": ate_threshold},
            }
        )

    if not windows:
        raise RuntimeError(f"{run}: no complete dropout windows")
    summary: dict[str, object] = {"windows": len(windows)}
    for stage, path in (
        ("pre_z_m", ("pre_error", "z_m")),
        ("pre_ate_m", ("pre_error", "ate_m")),
        ("imu_growth_z_m", ("imu_reconstruction_at_return", "z_growth_m")),
        ("imu_growth_ate_m", ("imu_reconstruction_at_return", "ate_growth_m")),
        ("first_return_z_m", ("first_return_error", "z_m")),
        ("first_return_ate_m", ("first_return_error", "ate_m")),
    ):
        values = [float(window[path[0]][path[1]]) for window in windows]
        summary[stage] = median_range(values)
    summary["recovered_both"] = {
        "count": sum(bool(window["recovered_within_2s"]["both"]) for window in windows),
        "fraction": sum(bool(window["recovered_within_2s"]["both"]) for window in windows)
        / len(windows),
    }
    return {
        "run": str(run.relative_to(ROOT)),
        "gap_s": gap_s,
        "reconstruction_status": (
            "analysis-layer IMU forward propagation from the last corrected "
            "state; not a directly logged high-rate LIO output"
        ),
        "recovery_rule": (
            "within 2 s, both |z| and 3D error return below "
            "max(0.05 m, 1.25 times the pre-gap error)"
        ),
        "summary": summary,
        "windows": windows,
    }


def main() -> int:
    m2_imu = load_imu(
        ROOT / "data/m2dgr/degraded/hall05_drop5x20.bag",
        "/handsfree/imu",
        np.eye(3),
    )
    m2_t0 = first_topic_stamp(
        ROOT / "data/m2dgr/hall_05/lidar_imu.bag", "/velodyne_points"
    )
    m2_ext = np.array([0.27255, -0.00053, 0.17954])
    analyses: dict[str, object] = {}
    hall_root = ROOT / "results/liosam_direction_dropout/m2dgr_hall05_drop5x20"
    for repeat in ("r1", "r2", "r3"):
        for variant in ("FG-BA", "GE-BA"):
            for level in ("off", "s2"):
                name = f"hall05_{variant}_{level}_{repeat}"
                analyses[name] = analyze_run(
                    hall_root / f"{variant}_{level}_{repeat}",
                    "m2dgr",
                    ROOT / "data/m2dgr/hall_05/gt/gt.txt",
                    m2_imu,
                    m2_t0,
                    5.0,
                    None,
                    m2_ext,
                )

    mcd_rotation = np.array(
        [
            [0.9999135040741837, -0.011166365511073898, -0.006949579221822984],
            [-0.011356389542502144, -0.9995453006865824, -0.02793249526856565],
            [-0.006634514801117132, 0.02800900135032654, -0.999585653686922],
        ]
    )
    mcd_imu = load_imu(
        ROOT / "data/mcd/tuhh_day_04/vn200.bag", "/vn200/imu", mcd_rotation
    )
    mcd_t0 = first_topic_stamp(
        ROOT / "data/mcd/tuhh_day_04/os1.bag", "/os_cloud_node/points"
    )
    mcd_ext = np.array(
        [-0.04894521120494695, -0.03126929060348084, -0.01755515794222565]
    )
    tuhh_runs = {
        "tuhh_FG-BA_off_r1": ROOT
        / "results/liosam_direction_dropout/mcd_tuhh_day04_drop5x20/FG-BA_off",
        "tuhh_FG-BA_s2_r1": ROOT
        / "results/liosam_direction_dropout/mcd_tuhh_day04_drop5x20/FG-BA_s2",
        "tuhh_GE-BA_off_r1": ROOT
        / "results/liosam_direction_dropout/mcd_tuhh_day04_drop5x20/GE-BA_off",
        "tuhh_GE-BA_s2_r1": ROOT
        / "results/liosam_direction_dropout/mcd_tuhh_day04_drop5x20/GE-BA_s2",
        "tuhh_GE-BA_off_r2": ROOT
        / "results/liosam_direction_repeats/mcd_tuhh_day04_drop5x20/GE-BA_off_r2",
        "tuhh_GE-BA_s2_r2": ROOT
        / "results/liosam_direction_repeats/mcd_tuhh_day04_drop5x20/GE-BA_s2_r2",
    }
    for name, run in tuhh_runs.items():
        analyses[name] = analyze_run(
            run,
            "mcd",
            ROOT / "data/mcd/tuhh_day_04/gt/pose_inW.csv",
            mcd_imu,
            mcd_t0,
            5.0,
            mcd_ext,
            None,
        )

    result = {
        "status": "mechanism_reconstruction_not_population_inference",
        "recovery_rule_preregistered_before_metric_collection": True,
        "analyses": analyses,
    }
    output = ROOT / "report/dropout_windows.json"
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"wrote {output} ({len(analyses)} runs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
