#!/usr/bin/env python3
"""Lock stronger-motion rosbag start phases before reading SLAM outcomes."""

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import collect_dynamic_init as base  # noqa: E402


# Playback begins 20 ms before the selected LiDAR scan.  These phases exceed
# the previous dynamic sweep in both apparent-gravity mismatch and mean gyro,
# while avoiding the most extreme spikes in each bag.
PHASES = [
    {"platform": "vehicle", "start_sec": 130.072,
     "sequence": "ntu_day_10_fastinit_s130p072"},
    {"platform": "vehicle", "start_sec": 189.471,
     "sequence": "ntu_day_10_fastinit_s189p471"},
    {"platform": "handheld", "start_sec": 70.572,
     "sequence": "tuhh_day_04_fastinit_s70p572"},
    {"platform": "handheld", "start_sec": 114.279,
     "sequence": "tuhh_day_04_fastinit_s114p279"},
]


def main() -> int:
    previous = json.loads((ROOT / "report" / "dynamic_init.json").read_text())
    previous_dynamic = {
        platform: [
            record for record in previous["records"]
            if record["platform"] == platform and record["regime"] == "dynamic"
        ]
        for platform in base.DATASETS
    }
    sensors = {platform: base.load_sensor_data(platform) for platform in base.DATASETS}

    records = []
    for phase in PHASES:
        platform = phase["platform"]
        window = base.selection_window(platform, phase["start_sec"], sensors[platform])
        prior_angle = max(
            record["selection_window"]["apparent_gravity_angle_deg"]
            for record in previous_dynamic[platform]
        )
        prior_gyro = max(
            record["selection_window"]["mean_gyro_norm_radps"]
            for record in previous_dynamic[platform]
        )
        remaining = float(sensors[platform]["lidar_t"][-1]
                          - window["first_selected_lidar_time"])
        if window["apparent_gravity_angle_deg"] <= prior_angle:
            raise RuntimeError(f"{phase['sequence']}: angle is not stronger than prior sweep")
        if window["mean_gyro_norm_radps"] <= max(0.08, prior_gyro):
            raise RuntimeError(f"{phase['sequence']}: gyro is not stronger than prior sweep")
        if window["mean_gyro_norm_radps"] >= 0.40:
            raise RuntimeError(f"{phase['sequence']}: gyro exceeds the pre-specified moderate-motion cap")
        if remaining < 60.0:
            raise RuntimeError(f"{phase['sequence']}: less than 60 s remains in the bag")
        records.append({
            **phase,
            "duration_sec": 60.0,
            "selection_window": window,
            "previous_dynamic_max": {
                "apparent_gravity_angle_deg": prior_angle,
                "mean_gyro_norm_radps": prior_gyro,
            },
            "remaining_lidar_duration_sec": remaining,
        })

    for platform in base.DATASETS:
        offsets = sorted(
            record["start_sec"] for record in records if record["platform"] == platform)
        if len(offsets) != 2 or offsets[1] - offsets[0] < 30.0:
            raise RuntimeError(f"{platform}: phases are not sufficiently separated")

    report = {
        "schema": 1,
        "status": "selection_locked_before_slam_outcomes",
        "selection_rule": {
            "purpose": "stress the shared acceleration-mean initializer with stronger natural motion",
            "outcome_blind": True,
            "requirements": [
                "apparent-gravity mismatch exceeds the prior dynamic sweep on the same trajectory",
                "mean gyro exceeds both 0.08 rad/s and the prior dynamic maximum",
                "mean gyro remains below 0.40 rad/s to avoid an extreme-turn-only test",
                "two starts per trajectory are separated by at least 30 s",
                "at least 60 s of LiDAR data remains after the selected scan",
            ],
        },
        "records": records,
    }
    output = ROOT / "report" / "dynamic_init_fast_selection.json"
    output.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    print(output)
    for record in records:
        window = record["selection_window"]
        print(
            f"{record['sequence']}: angle={window['apparent_gravity_angle_deg']:.2f} deg, "
            f"gyro={window['mean_gyro_norm_radps']:.3f} rad/s, "
            f"acc_std={window['acceleration_std_norm_mps2']:.2f} m/s^2"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
