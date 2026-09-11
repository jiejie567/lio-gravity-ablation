#!/usr/bin/env python3
"""Serial, fail-closed reproduction of the 12 nominal Online/FixG pairs.

No old run is overwritten. The first complete NTU Day02 pair is the gate for
the rest. This script must not be edited while it is running.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CAMPAIGN = ROOT / "results/strengthening_20260831"
SUFFIX = "_repro0831"
SEQUENCES = (
    "ntu_day_02_os1", "ntu_day_01_os1", "ntu_day_10_os1",
    "ntu_night_04_os1", "ntu_night_13_os1", "kth_day_10_os1",
    "kth_night_05_os1", "tuhh_day_02_os1", "tuhh_day_04_os1",
    "tuhh_night_09_os1", "IndoorOffice1", "hall_05_run",
)
LAUNCH = {"A": "mapping_exp", "RED21": "mapping_exp_redg"}
BINARIES = {"A": "fastlio_mapping", "RED21": "fastlio_mapping_redg"}


def now():
    return dt.datetime.now().astimezone().isoformat()


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def sha1(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha1").hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def settings(seq):
    if seq == "IndoorOffice1":
        return "data/tiers/IndoorOffice1", "configs/tiers_mid360.yaml", "2"
    if seq == "hall_05_run":
        return "data/m2dgr/hall_05_run", "configs/m2dgr_vlp32.yaml", "1.5"
    platform = "atv" if seq.startswith("ntu_") else "hhs"
    return f"data/mcd/{seq}", f"configs/mcd_{platform}_os1_imuint_off01.yaml", ("1.5" if platform == "atv" else "2")


def prepare():
    CAMPAIGN.mkdir(parents=True, exist_ok=True)
    path = CAMPAIGN / "fastlio_manifest.json"
    if path.exists():
        return json.loads(path.read_text())
    files = {Path(__file__).resolve(), ROOT / "scripts/run_experiment.sh",
             ROOT / "scripts/_run_in_container.sh", ROOT / "docker/run.sh",
             ROOT / "configs/exp_tuning.yaml"}
    source = ROOT / "catkin_ws/src/FAST_LIO"
    files.add(source / "CMakeLists.txt")
    for subdir in ("src", "include", "launch"):
        files.update(p for p in (source / subdir).rglob("*") if p.is_file())
    for seq in SEQUENCES:
        bag, config, _ = settings(seq)
        require((ROOT / bag).is_dir(), f"missing bag directory: {bag}")
        require(list((ROOT / bag).glob("*.bag")), f"empty bag directory: {bag}")
        files.add(ROOT / config)
    for name in BINARIES.values():
        files.add(ROOT / "catkin_ws/devel/lib/fast_lio" / name)
    snapshot = {str(p.relative_to(ROOT)): sha1(p) for p in sorted(files)}
    manifest = {
        "created_at": now(), "sequences": list(SEQUENCES), "runs": 24,
        "suffix": SUFFIX, "sha1": snapshot,
        "image_id": subprocess.check_output(["docker", "image", "inspect", "fastlio_exp:noetic", "--format", "{{.Id}}"], text=True).strip(),
        "build_check": "catkin_make -j2 -l2 fastlio_mapping fastlio_mapping_redg: both targets up to date before manifest creation",
        "settings": {s: settings(s) for s in SEQUENCES},
    }
    with tarfile.open(CAMPAIGN / "fastlio_source_and_binaries.tar.gz", "w:gz") as archive:
        for p in sorted(files):
            archive.add(p, arcname=str(p.relative_to(ROOT)), recursive=False)
    shutil.copy2(ROOT / "report/summary.json", CAMPAIGN / "summary_before.json")
    write_json(path, manifest)
    return manifest


def fingerprint_gate(manifest):
    for relative, expected in manifest["sha1"].items():
        require(sha1(ROOT / relative) == expected, f"frozen source/binary changed: {relative}")
    image_id = subprocess.check_output(["docker", "image", "inspect", "fastlio_exp:noetic", "--format", "{{.Id}}"], text=True).strip()
    require(image_id == manifest["image_id"], "container image changed")


def sleep_gate(start, end):
    result = subprocess.run(["pmset", "-g", "log"], capture_output=True, text=True,
                            errors="replace", timeout=60, check=True)
    require(bool(result.stdout.strip()), "empty pmset audit; cannot assume no sleep")
    hits = []
    for line in result.stdout.splitlines():
        if "Entering Sleep state" not in line:
            continue
        event = dt.datetime.strptime(" ".join(line.split()[:2]), "%Y-%m-%d %H:%M:%S").astimezone()
        if dt.datetime.fromisoformat(start) <= event <= dt.datetime.fromisoformat(end):
            hits.append(line)
    require(not hits, f"sleep overlaps run: {hits}")
    return {"checked_at": now(), "events_in_run": 0, "pmset_returncode": result.returncode}


def load_complete(path):
    frame = pd.read_csv(path)
    require(len(frame) > 10 and np.isfinite(frame.to_numpy(dtype=float)).all(), f"empty, truncated or non-finite CSV: {path}")
    require(np.all(np.diff(frame.t) > 0), f"non-monotonic timestamps: {path}")
    frame.attrs["timestamp_text"] = pd.read_csv(path, usecols=["t"], dtype=str).t.tolist()
    return frame


def validate_pair(seq, manifest):
    historical = json.loads((CAMPAIGN / "summary_before.json").read_text())["sequences"][seq]
    require(historical["gt"]["usable"], f"unusable ground truth: {seq}")
    expected_frames = historical["runs"]["A"]["log_lines"] - 1
    frames = {m: load_complete(ROOT / "results" / seq / (m + SUFFIX) / "state_log.csv") for m in BINARIES}
    records = {}
    for method, frame in frames.items():
        run = ROOT / "results" / seq / (method + SUFFIX)
        completion = json.loads((run / "campaign_completion.json").read_text())
        require(completion["returncode"] == 0, f"runner failed: {run}")
        require(len(frame) == expected_frames, f"{seq}/{method}: {len(frame)} frames != historical {expected_frames}")
        require(frame.attrs["timestamp_text"] == frames["A"].attrs["timestamp_text"], f"{seq}: pair timestamps differ")
        g = frame[["gx", "gy", "gz"]].to_numpy()
        departure = float(np.abs(g - g[0]).max())
        require(departure <= 1e-12 if method == "RED21" else departure > 1e-12, f"{method}: incorrect gravity state structure")
        for fields in (("bax", "bay", "baz"), ("bgx", "bgy", "bgz")):
            values = frame[list(fields)].to_numpy()
            require(np.abs(values - values[0]).max() > 1e-12, f"{method}: online {fields} is constant")
        norm_error = float(np.abs(np.linalg.norm(g, axis=1) - 9.8090).max())
        require(norm_error < 1e-7, f"{method}: wrong gravity norm {norm_error}")
        g0 = frames["A"][["gx", "gy", "gz"]].iloc[0].to_numpy()
        angle = float(np.degrees(np.arccos(np.clip(g[0] @ g0 / np.linalg.norm(g[0]) / np.linalg.norm(g0), -1, 1))))
        require(angle < 0.1, f"{method}: initialization direction differs by {angle} deg")
        arc = float(np.linalg.norm(np.diff(frame[["px", "py", "pz"]], axis=0), axis=1).sum())
        ratio = arc / historical["gt"]["path_len_m"]
        require(0.6 <= ratio <= 1.6, f"{method}: arc-length gate failed: {ratio}")
        meta = dict(line.split(": ", 1) for line in (run / "run_meta.txt").read_text().splitlines() if ": " in line)
        binary = f"catkin_ws/devel/lib/fast_lio/{BINARIES[method]}"
        require(meta.get("fastlio_binary_sha1") == manifest["sha1"][binary][:12], f"{method}: launched binary hash mismatch")
        require(meta.get("launch") == LAUNCH[method], f"{method}: wrong launch")
        require("freeze_gravity=false freeze_ba=false freeze_bg=false grav_err=0 freeze_after_sec=-1 warm_fixg_after_sec=-1" in meta["method"], f"{method}: runtime intervention enabled")
        audit = sleep_gate(completion["started_at"], completion["finished_at"])
        records[method] = {"frames": len(frame), "arc_ratio": ratio,
                           "gravity_norm_max_error": norm_error, "initial_angle_deg": angle,
                           "gravity_max_component_change": departure, "sleep": audit,
                           "binary_sha1": manifest["sha1"][binary], "state_sha1": sha1(run / "state_log.csv")}
    write_json(CAMPAIGN / f"validation_{seq}.json", {"passed": True, "sequence": seq, "runs": records})
    print(f"PAIR GATE PASS {seq}: {expected_frames} identical correction timestamps", flush=True)


def run_one(seq, method, manifest):
    run = ROOT / "results" / seq / (method + SUFFIX)
    marker = run / "campaign_completion.json"
    if marker.exists():
        require(json.loads(marker.read_text())["returncode"] == 0, f"failed existing attempt: {run}")
        print(f"RECHECK completed {seq}/{method}", flush=True)
        return
    require(not run.exists(), f"partial output requires inspection, refusing overwrite: {run}")
    fingerprint_gate(manifest)
    bag, config, rate = settings(seq)
    command = [str(ROOT / "scripts/run_experiment.sh"), "A", bag, "-c", "/work/" + config,
               "-x", "configs/exp_tuning.yaml", "-n", method + SUFFIX,
               "-L", LAUNCH[method], "-r", rate, "-p"]
    started = now()
    write_json(CAMPAIGN / "fastlio_status.json", {"status": "running", "sequence": seq, "method": method, "started_at": started, "pid": os.getpid()})
    print(f"START {seq}/{method} {started}", flush=True)
    with (CAMPAIGN / f"console_{seq}_{method}.log").open("x") as output:
        result = subprocess.run(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
    completion = {"started_at": started, "finished_at": now(), "returncode": result.returncode, "command": command}
    if run.exists():
        write_json(marker, completion)
    require(result.returncode == 0, f"runner exited {result.returncode}: {seq}/{method}")
    print(f"FINISH {seq}/{method} {completion['finished_at']}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--pilot-only", action="store_true")
    args = parser.parse_args()
    manifest = prepare()
    fingerprint_gate(manifest)
    if args.prepare_only:
        print(f"Prepared immutable manifest: {CAMPAIGN / 'fastlio_manifest.json'}")
        return
    lock = ROOT / ".chain.lock"
    lock.mkdir()  # Never steal or bypass another queue's lock.
    (lock / "pid").write_text(str(os.getpid()) + "\n")
    (lock / "what").write_text("FAST-LIO2 nominal reproduction 20260831\n")
    try:
        require(not (ROOT / ".run.lock").exists(), "an experiment is already active")
        for index, seq in enumerate(SEQUENCES[:1] if args.pilot_only else SEQUENCES):
            order = ("A", "RED21") if index % 2 == 0 else ("RED21", "A")
            for method in order:
                run_one(seq, method, manifest)
            validate_pair(seq, manifest)
        status = "pilot_passed" if args.pilot_only else "runs_validated_analysis_pending"
        write_json(CAMPAIGN / "fastlio_status.json", {"status": status, "finished_at": now(), "pid": os.getpid()})
    except BaseException as exc:
        write_json(CAMPAIGN / "fastlio_status.json", {"status": "stopped_for_audit", "error": str(exc), "at": now(), "pid": os.getpid()})
        raise
    finally:
        (lock / "pid").unlink()
        (lock / "what").unlink()
        lock.rmdir()


if __name__ == "__main__":
    main()
