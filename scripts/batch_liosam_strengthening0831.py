#!/usr/bin/env python3
"""Run the pre-specified LIO-SAM extension after the FAST-LIO reproduction.

Reuse only explicitly enumerated, fingerprinted off/2-degree controls. There
are 30 new dropout runs and eight new full-sequence state-ablation runs. Any
failed gate stops the queue without deleting, retrying or selecting outcomes.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile

import numpy as np
from rosbags.rosbag1 import Reader

from batch_fastlio_repro0831 import ROOT, CAMPAIGN, now, require, sha1, write_json
from collect_liosam_direction import collect_sequence
from collect_liosam_mcd_pilot import load_estimate, load_gt

LEVELS = {"off": 0.0, "s0p5": math.radians(0.5), "s2": math.radians(2), "s5": math.radians(5)}
VARIANTS = ("FG-BA", "GE-BA")
STATE_VARIANTS = ("FG-BA", "FG-B0", "GE-BA", "GE-B0")
WEIGHTS = {
    "hall05": {"dataset": "m2dgr", "bag": "data/m2dgr/degraded/hall05_drop5x20.bag", "duration": "400", "rate": "0.5", "gt": "data/m2dgr/hall_05/gt/gt.txt", "state_frames": 1498, "odom_frames": 1499},
    "tuhh_day04": {"dataset": "mcd", "bag": "data/mcd/degraded/tuhh_day_04_drop5x20.bag", "imu": "data/mcd/tuhh_day_04/vn200.bag", "duration": "187", "rate": "0.25", "gt": "data/mcd/tuhh_day_04/gt/pose_inW.csv", "state_frames": 709, "odom_frames": 710},
}
HOLDOUTS = {
    "ntu_day_02": {"setup": "atv", "duration": "229", "imu": "vn100"},
    "tuhh_night_09": {"setup": "handheld", "duration": "185", "imu": "vn200"},
}


def reused_control(dataset, variant, level, repeat):
    if level not in ("off", "s2"):
        return None
    if dataset == "hall05":
        return ROOT / "results/liosam_direction_dropout/m2dgr_hall05_drop5x20" / f"{variant}_{level}_r{repeat}"
    if repeat == 1:
        return ROOT / "results/liosam_direction_dropout/mcd_tuhh_day04_drop5x20" / f"{variant}_{level}"
    if repeat == 2 and variant == "GE-BA":
        return ROOT / "results/liosam_direction_repeats/mcd_tuhh_day04_drop5x20" / f"{variant}_{level}_r2"
    return None


def metadata(run):
    return dict(line.split("=", 1) for line in (run / "run_meta.txt").read_text().splitlines() if "=" in line)


def rows(path):
    with path.open() as handle:
        return list(csv.DictReader(handle))


def sleep_audit(run):
    meta = metadata(run)
    start = dt.datetime.fromisoformat(meta["started_at"].replace("Z", "+00:00"))
    end = dt.datetime.fromisoformat(meta["finished_at"].replace("Z", "+00:00"))
    completed = subprocess.run(["pmset", "-g", "log"], capture_output=True, text=True, errors="replace", check=True, timeout=60)
    dated = []
    hits = []
    for line in completed.stdout.splitlines():
        if not re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", line):
            continue
        stamp = dt.datetime.strptime(line[:19], "%Y-%m-%d %H:%M:%S").astimezone()
        dated.append(stamp)
        if "Entering Sleep state" in line and start <= stamp <= end:
            hits.append(line)
    require(dated and min(dated) <= start, f"pmset history does not cover {run}")
    require(not hits, f"sleep contaminated {run}: {hits}")
    return {"checked_at": now(), "events": 0, "history_start": min(dated).isoformat()}


def prepare():
    path = CAMPAIGN / "liosam_manifest.json"
    if path.exists():
        return json.loads(path.read_text())
    CAMPAIGN.mkdir(parents=True, exist_ok=True)
    files = {Path(__file__).resolve(), ROOT / "scripts/batch_fastlio_repro0831.py"}
    for name in ("run_liosam_gravity_direction.sh", "run_liosam_mcd_gravity_direction.sh", "run_liosam_mcd_ablation.sh", "run_liosam_inside.sh", "run_liosam_mcd_inside.sh", "validate_liosam_direction_sweep.py", "validate_liosam_ablation.py", "collect_liosam_direction.py", "collect_liosam_mcd_full.py", "collect_liosam_mcd_pilot.py"):
        files.add(ROOT / "scripts" / name)
    source = ROOT / "liosam_ws/src/LIO-SAM"
    files.add(source / "CMakeLists.txt")
    for subdir in ("src", "include", "launch", "config"):
        files.update(p for p in (source / subdir).rglob("*") if p.is_file())
    files.update(p for p in (ROOT / "liosam_ws/devel/lib/lio_sam").glob("lio_sam_*") if p.is_file())
    files.update(ROOT / "data/mcd/calib" / name for name in ("atv_calib_file", "handheld_calib_file"))
    controls = {}
    for dataset in WEIGHTS:
        for repeat in (1, 2, 3):
            for variant in VARIANTS:
                for level in ("off", "s2"):
                    run = reused_control(dataset, variant, level, repeat)
                    if run is None:
                        continue
                    require(run.is_dir(), f"missing prescribed reusable control: {run}")
                    meta = metadata(run)
                    require("finished_at" in meta, f"unfinished control: {run}")
                    require(sha1(ROOT / "liosam_ws/devel/lib/lio_sam" / meta["imu_node"]) == meta["binary_sha1"], f"control binary mismatch: {run}")
                    control_files = [p for p in run.iterdir() if p.is_file() and p.suffix in (".csv", ".txt", ".log")]
                    controls[str(run.relative_to(ROOT))] = {"sha1": {p.name: sha1(p) for p in control_files}, "sleep_audit": sleep_audit(run)}
    inputs = {}
    input_paths = set()
    for config in WEIGHTS.values():
        input_paths.update(config[k] for k in ("bag", "gt", "imu") if k in config)
    for seq, config in HOLDOUTS.items():
        input_paths.update((f"data/mcd/{seq}/os1.bag", f"data/mcd/{seq}/{config['imu']}.bag", f"data/mcd/{seq}/gt/pose_inW.csv"))
    for relative in sorted(input_paths):
        p = ROOT / relative
        require(p.is_file(), f"missing input: {relative}")
        info = {"bytes": p.stat().st_size, "mtime_ns": p.stat().st_mtime_ns, "sha1": sha1(p)}
        if p.suffix == ".bag":
            with Reader(p) as reader:
                info.update({"start_ns": reader.start_time, "end_ns": reader.end_time,
                             "topics": {c.topic: c.msgcount for c in reader.connections}})
        inputs[relative] = info
    manifest = {"created_at": now(), "new_dropout_runs": 30, "reused_controls": controls,
                "holdouts": HOLDOUTS, "new_holdout_runs": 8, "weights": WEIGHTS,
                "levels_rad": LEVELS, "inputs": inputs,
                "sha1": {str(p.relative_to(ROOT)): sha1(p) for p in sorted(files)},
                "image_id": subprocess.check_output(["docker", "image", "inspect", "liosam_exp:noetic", "--format", "{{.Id}}"], text=True).strip()}
    with tarfile.open(CAMPAIGN / "liosam_source_and_binaries.tar.gz", "w:gz") as archive:
        for p in sorted(files):
            archive.add(p, arcname=str(p.relative_to(ROOT)), recursive=False)
    for name in ("liosam_full.json", "liosam_direction.json"):
        shutil.copy2(ROOT / "report" / name, CAMPAIGN / (Path(name).stem + "_before.json"))
    write_json(path, manifest)
    return manifest


def fingerprint_gate(manifest):
    for relative, expected in manifest["sha1"].items():
        require(sha1(ROOT / relative) == expected, f"source/binary changed: {relative}")
    for relative, info in manifest["inputs"].items():
        stat = (ROOT / relative).stat()
        require((stat.st_size, stat.st_mtime_ns) == (info["bytes"], info["mtime_ns"]), f"input changed: {relative}")
    current = subprocess.check_output(["docker", "image", "inspect", "liosam_exp:noetic", "--format", "{{.Id}}"], text=True).strip()
    require(current == manifest["image_id"], "LIO-SAM image changed")


def run_one(command, run, manifest):
    completion = run / "campaign_completion.json"
    if completion.exists():
        require(json.loads(completion.read_text())["returncode"] == 0, f"previous failed run: {run}")
        return
    require(not run.exists(), f"partial run requires inspection: {run}")
    fingerprint_gate(manifest)
    started = now()
    write_json(CAMPAIGN / "liosam_status.json", {"status": "running", "run": str(run.relative_to(ROOT)), "started_at": started, "pid": os.getpid()})
    print(f"START {run.relative_to(ROOT)} {started}", flush=True)
    log = CAMPAIGN / ("console_" + "_".join(run.relative_to(CAMPAIGN).parts) + ".log")
    with log.open("x") as handle:
        result = subprocess.run(command, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT)
    if run.exists():
        write_json(completion, {"started_at": started, "finished_at": now(), "returncode": result.returncode, "command": command})
    require(result.returncode == 0, f"runner failed {result.returncode}: {run}")
    write_json(run / "campaign_sleep.json", sleep_audit(run))
    print(f"FINISH {run.relative_to(ROOT)} {now()}", flush=True)


def validate_weights(grid, config):
    result = subprocess.run([sys.executable, str(ROOT / "scripts/validate_liosam_direction_sweep.py"), str(grid)], text=True, capture_output=True)
    (grid / "validation.log").write_text(result.stdout + result.stderr)
    require(result.returncode == 0, f"direction sweep gate failed: {grid}; see validation.log (do not discard failed outcomes)")
    for variant in VARIANTS:
        for level in LEVELS:
            run = grid / f"{variant}_{level}"
            require(len(rows(run / "state_log.csv")) == config["state_frames"], f"historical state frame count mismatch: {run}")
            require(len(rows(run / "odometry.csv")) == config["odom_frames"], f"historical odometry count mismatch: {run}")
    metrics = collect_sequence(grid.parent.name, grid, config["dataset"], ROOT / config["gt"], tuple(LEVELS))
    write_json(grid / "metrics.json", metrics)
    write_json(grid / "validation.json", {"passed": True, "validated_at": now()})
    print(f"DIRECTION GATE PASS {grid.relative_to(ROOT)}", flush=True)


def weight_sweep(manifest):
    for dataset, config in WEIGHTS.items():
        for repeat in (1, 2, 3):
            grid = CAMPAIGN / "liosam_weights" / dataset / f"r{repeat}"
            grid.mkdir(parents=True, exist_ok=True)
            levels = ("off", "s2", "s0p5", "s5") if repeat != 2 else ("off", "s2", "s5", "s0p5")
            for variant in VARIANTS:
                for level in levels:
                    run = grid / f"{variant}_{level}"
                    reference = reused_control(dataset, variant, level, repeat)
                    if reference is not None:
                        frozen = manifest["reused_controls"][str(reference.relative_to(ROOT))]
                        for name, digest in frozen["sha1"].items():
                            require(sha1(reference / name) == digest, f"reused output changed: {reference / name}")
                        if not run.exists():
                            run.symlink_to(reference, target_is_directory=True)
                        require(run.resolve() == reference.resolve(), f"incorrect reused control: {run}")
                        continue
                    output = str(run.relative_to(ROOT))
                    sigma = str(LEVELS[level])
                    if dataset == "hall05":
                        command = ["bash", "scripts/run_liosam_gravity_direction.sh", variant, config["bag"], output, sigma, "0", config["duration"], config["rate"]]
                    else:
                        command = ["bash", "scripts/run_liosam_mcd_gravity_direction.sh", variant, "handheld", config["bag"], config["imu"], output, sigma, "0", config["duration"], config["rate"]]
                    run_one(command, run, manifest)
            validate_weights(grid, config)  # r1 must pass before r2/r3.


def holdouts(manifest):
    for seq, config in HOLDOUTS.items():
        grid = CAMPAIGN / "liosam_holdout" / seq
        for variant in STATE_VARIANTS:
            run = grid / variant
            command = ["bash", "scripts/run_liosam_mcd_ablation.sh", variant, config["setup"], f"data/mcd/{seq}/os1.bag", f"data/mcd/{seq}/{config['imu']}.bag", str(run.relative_to(ROOT)), "0", config["duration"], "0.25"]
            run_one(command, run, manifest)
        result = subprocess.run([sys.executable, str(ROOT / "scripts/validate_liosam_ablation.py"), str(grid)], text=True, capture_output=True)
        (grid / "validation.log").write_text(result.stdout + result.stderr)
        require(result.returncode == 0, f"held-out state gate failed: {grid}")
        gt_path = ROOT / f"data/mcd/{seq}/gt/pose_inW.csv"
        gt_time, gt_position = load_gt(gt_path)
        reference_times = [r["%time"] for r in rows(grid / "FG-BA/odometry.csv")]
        arcs = {}
        for variant in STATE_VARIANTS:
            require([r["%time"] for r in rows(grid / variant / "odometry.csv")] == reference_times, f"{seq}: exact odometry timestamps differ")
            time, positions = load_estimate(grid / variant / "odometry.csv", config["setup"])
            valid = (time >= gt_time[0]) & (time <= gt_time[-1])
            require(valid.sum() > 10, f"{seq}: insufficient GT overlap")
            time, positions = time[valid], positions[valid]
            truth = np.column_stack([np.interp(time, gt_time, gt_position[:, axis]) for axis in range(3)])
            ratio = float(np.linalg.norm(np.diff(positions, axis=0), axis=1).sum() / np.linalg.norm(np.diff(truth, axis=0), axis=1).sum())
            require(0.6 <= ratio <= 1.6, f"{seq}/{variant}: arc-length gate failed: {ratio}")
            require(time[-1] - time[0] >= 0.97 * (gt_time[-1] - gt_time[0]), f"{seq}: truncated trajectory")
            arcs[variant] = ratio
        subprocess.run([sys.executable, str(ROOT / "scripts/collect_liosam_mcd_full.py"), str(grid), config["setup"], seq, str(gt_path), str(grid / "metrics.json")], check=True, stdout=subprocess.DEVNULL)
        write_json(grid / "validation.json", {"passed": True, "validated_at": now(), "arc_ratios": arcs})
        print(f"HOLDOUT GATE PASS {seq}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    if args.prepare_only:
        manifest = prepare()
        fingerprint_gate(manifest)
        print("LIO-SAM strengthening manifest prepared; no experiments started")
        return
    lock = ROOT / ".chain.lock"
    lock.mkdir()
    (lock / "pid").write_text(str(os.getpid()) + "\n")
    (lock / "what").write_text("LIO-SAM strengthening 20260831\n")
    try:
        require(not (ROOT / ".run.lock").exists(), "another experiment is active")
        manifest = prepare()
        fingerprint_gate(manifest)
        weight_sweep(manifest)
        holdouts(manifest)
        write_json(CAMPAIGN / "liosam_status.json", {"status": "runs_validated", "finished_at": now()})
    except BaseException as exc:
        write_json(CAMPAIGN / "liosam_status.json", {"status": "stopped_for_audit", "error": str(exc), "at": now()})
        raise
    finally:
        (lock / "pid").unlink()
        (lock / "what").unlink()
        lock.rmdir()


if __name__ == "__main__":
    main()
