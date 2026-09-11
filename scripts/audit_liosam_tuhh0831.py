#!/usr/bin/env python3
"""Audit the TUHH arc alarm without changing or bypassing accuracy admission."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

import numpy as np
import pandas as pd

import batch_liosam_strengthening0831 as batch
import collect_liosam_direction as metrics
import validate_liosam_direction_sweep as gate
from batch_fastlio_repro0831 import ROOT, CAMPAIGN, now, require, sha1, write_json

ARCHIVE = CAMPAIGN / "audit_tuhh_arc_20260831"
ARC_FAILURE = "arc_gate_failure_not_accuracy_run"
REVIEWED_CELL = "FG-BA_s0p5"
ARC_WARNING = "observed_arc_gate_accuracy_outcome"
FOLLOWUP = CAMPAIGN / "audit_tuhh_arc_followup_20260901"
RAW_FILES = {"state_log.csv", "odometry.csv", "gravity_direction.csv", "run_meta.txt",
             "launch.log", "rosbag.log", "roscore.log", "odometry_stderr.log",
             "campaign_completion.json", "campaign_sleep.json"}


def classify_arc(name, ratio):
    require(np.isfinite(ratio), f"nonfinite arc ratio: {name}")
    if 0.6 <= ratio <= 1.6:
        return "admitted_accuracy"
    return ARC_WARNING


def accuracy_without_arc_rejection(run, gt_time, gt_position):
    """Use the unchanged alignment/metrics when valid GT exposes estimator failure."""
    time, estimate = metrics.load_estimate(run / "odometry.csv", "mcd")
    valid = (time >= gt_time[0]) & (time <= gt_time[-1])
    time, estimate = time[valid], estimate[valid]
    truth = np.column_stack([np.interp(time, gt_time, gt_position[:, i]) for i in range(3)])
    align_count = max(10, int(np.searchsorted(time, time[0] + 10.0)))
    rotation, translation = metrics.rigid_alignment(estimate[:align_count], truth[:align_count])
    aligned = estimate @ rotation.T + translation
    error = aligned - truth
    error_norm = np.linalg.norm(error, axis=1)
    gt_arc = float(np.linalg.norm(np.diff(truth, axis=0), axis=1).sum())
    estimate_arc = float(np.linalg.norm(np.diff(aligned, axis=0), axis=1).sum())
    result = {
        "frames": int(len(time)), "duration_s": float(time[-1] - time[0]),
        "gt_arc_length_m": gt_arc, "estimate_to_gt_arc_ratio": estimate_arc / gt_arc,
        "rmse_z_m": float(np.sqrt(np.mean(error[:, 2] ** 2))),
        "ate_rmse_m": float(np.sqrt(np.mean(error_norm ** 2))),
        "rmse_z_mm_per_100m": float(np.sqrt(np.mean(error[:, 2] ** 2))) / gt_arc * 100000.0,
        "ate_mm_per_100m": float(np.sqrt(np.mean(error_norm ** 2))) / gt_arc * 100000.0,
        "final_position_error_m": float(error_norm[-1]),
    }
    direction = metrics.direction_stats(run / "gravity_direction.csv")
    if direction is not None:
        result["direction_factor"] = direction
    return result


def arc_diagnostics(run, gt_time, gt_position):
    time, estimate = metrics.load_estimate(run / "odometry.csv", "mcd")
    valid = (time >= gt_time[0]) & (time <= gt_time[-1])
    time, estimate = time[valid], estimate[valid]
    require(len(time) > 10 and np.all(np.diff(time) > 0), f"GT overlap/time ordering: {run}")
    require(time[-1] - time[0] >= .97 * (gt_time[-1] - gt_time[0]), f"truncated trajectory: {run}")
    truth = np.column_stack([np.interp(time, gt_time, gt_position[:, i]) for i in range(3)])
    est_steps = np.linalg.norm(np.diff(estimate, axis=0), axis=1)
    gt_steps = np.linalg.norm(np.diff(truth, axis=0), axis=1)
    require(gt_steps.sum() > 0, "stationary GT")
    gaps = np.flatnonzero(np.diff(time) > 1.0)
    return {
        "gt_overlap_rows": len(time), "gt_arc_length_m": float(gt_steps.sum()),
        "estimated_arc_length_m": float(est_steps.sum()),
        "estimate_to_gt_arc_ratio": float(est_steps.sum() / gt_steps.sum()),
        "gap_transition_arc_m": float(est_steps[gaps].sum()),
        "nongap_arc_m": float(est_steps.sum() - est_steps[gaps].sum()),
        "gap_transitions": [{"end_s_from_first_matched_pose": float(time[i + 1] - time[0]),
                             "duration_s": float(time[i + 1] - time[i]),
                             "estimate_step_m": float(est_steps[i]), "gt_step_m": float(gt_steps[i])}
                            for i in gaps],
    }


def inspect_round(grid):
    manifest = json.loads((CAMPAIGN / "liosam_manifest.json").read_text())
    batch.fingerprint_gate(manifest)
    result = subprocess.run([sys.executable, str(ROOT / "scripts/validate_liosam_direction_sweep.py"),
                             str(grid)], text=True, capture_output=True)
    require(result.returncode == 0, f"unchanged structural gate failed: {grid}\n{result.stdout}{result.stderr}")
    config = batch.WEIGHTS["tuhh_day04"]
    gt_time, gt_position = metrics.load_gt(ROOT / config["gt"], "mcd")
    require(np.isfinite(gt_position).all() and np.all(np.diff(gt_time) > 0), "invalid GT contents")
    cells = {}
    for variant in batch.VARIANTS:
        for level in batch.LEVELS:
            name = f"{variant}_{level}"
            run = grid / name
            meta = batch.metadata(run)
            expected = {"dataset": "mcd", "setup": "handheld", "lidar_bag": config["bag"],
                        "imu_bag": config["imu"], "start_s": "0", "duration_s": config["duration"],
                        "rate": config["rate"], "gravity_direction_source": "sensor_msgs/Imu.orientation",
                        "container_image_id": manifest["image_id"]}
            require(all(meta.get(k) == v for k, v in expected.items()), f"input/execution metadata: {run}")
            state, odom = gate.read_csv(run / "state_log.csv"), gate.read_csv(run / "odometry.csv")
            require(len(state) == config["state_frames"] and len(odom) == config["odom_frames"], f"historical frame counts: {run}")
            values = pd.DataFrame(state).drop(columns="variant").astype(float).to_numpy()
            require(np.isfinite(values).all(), f"nonfinite state: {run}")
            values = pd.DataFrame(odom)[list(metrics.POS + metrics.QUAT)].astype(float).to_numpy()
            require(np.isfinite(values).all(), f"nonfinite odometry: {run}")
            if run.is_symlink():
                frozen = manifest["reused_controls"][str(run.resolve().relative_to(ROOT))]
                require(all(sha1(run / f) == digest for f, digest in frozen["sha1"].items()), f"changed reused control: {run}")
                sleep = frozen["sleep_audit"]
            else:
                require(json.loads((run / "campaign_completion.json").read_text())["returncode"] == 0, f"runner failed: {run}")
                sleep = batch.sleep_audit(run)
            require(sleep["events"] == 0, f"sleep contamination: {run}")
            diagnostic = arc_diagnostics(run, gt_time, gt_position)
            status = classify_arc(name, diagnostic["estimate_to_gt_arc_ratio"])
            cell = {"path": str(run.relative_to(ROOT)), "status": status,
                    "state_rows": len(state), "odometry_rows": len(odom), "sleep": sleep,
                    "diagnostics": diagnostic,
                    "sha1": {p.name: sha1(p) for p in run.iterdir() if p.is_file() and p.name in RAW_FILES}}
            if status == "admitted_accuracy":
                # The original arc check remains authoritative for all accuracy values.
                cell["metrics"] = metrics.evaluate_run(run, "mcd", gt_time, gt_position)
            elif status == ARC_FAILURE:
                try:
                    metrics.evaluate_run(run, "mcd", gt_time, gt_position)
                except RuntimeError as exc:
                    require("arc-length gate failed" in str(exc), f"unexpected evaluator error: {exc}")
                    cell["original_gate_error"] = str(exc)
                else:
                    raise RuntimeError("original arc gate unexpectedly admitted failed outcome")
            else:
                try:
                    metrics.evaluate_run(run, "mcd", gt_time, gt_position)
                except RuntimeError as exc:
                    require("arc-length gate failed" in str(exc), f"unexpected evaluator error: {exc}")
                    cell["original_gate_warning"] = str(exc)
                else:
                    raise RuntimeError("original arc gate did not reproduce warning")
                cell["metrics"] = accuracy_without_arc_rejection(run, gt_time, gt_position)
            cells[name] = cell
    # GT usability is established by both off estimators and the independent
    # FAST-LIO validation. A non-baseline method leaving this range is an
    # estimator outcome, not evidence that the shared GT became invalid.
    require(all(cells[f"{v}_off"]["status"] == "admitted_accuracy" for v in batch.VARIANTS), "baseline/GT gate failed")
    return {"audited_at": now(), "structural_validation_stdout": result.stdout, "cells": cells,
            "interpretation": "With usable shared GT and complete finite outputs, excess estimated travel is retained as a flagged accuracy outcome. It is not proof of factor causality; low-level IMU receipt timing was not recorded."}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--followup", action="store_true")
    args = parser.parse_args()
    require(not (ROOT / ".run.lock").exists() and not (ROOT / ".chain.lock").exists(), "experiment active")
    output_dir = FOLLOWUP if args.followup else ARCHIVE
    require(not (output_dir / "audit.json").exists(), "audit is immutable")
    manifest = json.loads((CAMPAIGN / "liosam_manifest.json").read_text())
    inputs = {}
    for key in ("bag", "imu", "gt"):
        relative = batch.WEIGHTS["tuhh_day04"][key]
        inputs[relative] = sha1(ROOT / relative)
        require(inputs[relative] == manifest["inputs"][relative]["sha1"], f"changed input contents: {relative}")
        print(f"INPUT SHA1 PASS {relative}", flush=True)
    rounds = (1, 2, 3) if args.followup else (1,)
    reports = {str(r): inspect_round(CAMPAIGN / f"liosam_weights/tuhh_day04/r{r}") for r in rounds}
    first_status = reports["1"]["cells"][REVIEWED_CELL]["status"]
    require(first_status == (ARC_WARNING if args.followup else ARC_FAILURE), "reviewed first-round outcome changed")
    since, until, expected = (("2026-08-31T23:59:30+08:00", "2026-09-01T03:01:00+08:00", 14)
                              if args.followup else ("2026-08-31T21:21:00+08:00", "2026-08-31T22:13:00+08:00", 4))
    text = subprocess.check_output(["docker", "events", "--since", since,
                                    "--until", until, "--format", "{{json .}}"], text=True)
    active, events = set(), []
    for line in text.splitlines():
        event = json.loads(line)
        if event.get("Type") != "container" or event.get("Action") not in ("start", "die", "oom", "kill"):
            continue
        action, actor = event["Action"], event["Actor"]
        if action == "start":
            active.add(actor["ID"])
            require(len(active) == 1, "concurrent containers")
        elif action == "die":
            require(actor["ID"] in active and actor["Attributes"].get("exitCode") == "0", "failed container")
            active.remove(actor["ID"])
        else:
            raise RuntimeError(f"container event: {action}")
        events.append(event)
    require(not active and sum(e["Action"] == "start" for e in events) == expected, "incomplete container history")
    report = {"audited_at": now(), "rounds": reports, "input_sha1": inputs,
              "serial_container_events": events,
              "policy": ("Shared GT is independently usable. Complete finite estimator outputs outside the arc range retain metrics plus an arc warning; no replacement or threshold change. Structural, timestamp, reset, sleep and concurrency failures still stop."
                         if args.followup else "Initial pre-repeat policy retained for historical audit.")}
    write_json(output_dir / "audit.json", report)
    target = ROOT / ("report/strengthening_tuhh_followup_audit_20260901.json" if args.followup else "report/strengthening_tuhh_audit_20260831.json")
    write_json(target, report)
    for repeat, item in reports.items():
        for name, cell in item["cells"].items():
            print(repeat, name, cell["status"], cell["diagnostics"]["estimate_to_gt_arc_ratio"])


if __name__ == "__main__":
    main()
