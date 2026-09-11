#!/usr/bin/env python3
"""Audit every Hall05 cell without admitting reset or timestamp-mismatched runs."""
from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess

import numpy as np
import pandas as pd

import batch_liosam_strengthening0831 as batch
import validate_liosam_direction_sweep as gate
from batch_fastlio_repro0831 import ROOT, CAMPAIGN, now, require, sha1, write_json
from collect_liosam_direction import evaluate_run, load_gt

FAILED = "r3/FG-BA_s5"
PHASE = "r3/FG-BA_s0p5"
GRID = CAMPAIGN / "liosam_weights/hall05"
PHASE_ARCHIVE = ROOT / "quarantine/liosam_hall05_s0p5_timestamp_20260831"


def inspect():
    manifest = json.loads((CAMPAIGN / "liosam_manifest.json").read_text())
    batch.fingerprint_gate(manifest)
    gt_time, gt_position = load_gt(ROOT / batch.WEIGHTS["hall05"]["gt"], "m2dgr")
    cells = {}
    for repeat in (1, 2, 3):
        reference = GRID / f"r{repeat}/FG-BA_off"
        ref_s = gate.read_csv(reference / "state_log.csv")
        ref_o = gate.read_csv(reference / "odometry.csv")
        st = [r["timestamp"] for r in ref_s]
        ot = [r["%time"] for r in ref_o]
        gravity_norm = np.linalg.norm(gate.vector(ref_s[0], ("gx", "gy", "gz")))
        for variant in batch.VARIANTS:
            for level, sigma in batch.LEVELS.items():
                name = f"r{repeat}/{variant}_{level}"
                run = GRID / name
                meta = batch.metadata(run)
                require(meta["variant"] == variant and meta["dataset"] == "m2dgr", f"metadata: {name}")
                require(meta["imu_node"] == gate.expected_node(variant, level != "off"), f"node: {name}")
                require(meta["gravity_direction_mode"] == ("OFF" if level == "off" else "ON"), f"mode: {name}")
                require(math.isclose(float(meta["gravity_direction_sigma_rad"]), sigma, abs_tol=1e-14, rel_tol=0), f"sigma: {name}")
                require(meta["omp_num_threads"] == "1" and float(meta["rate"]) == 0.5 and "finished_at" in meta, f"execution metadata: {name}")
                for path, key in ((ROOT / "liosam_ws/devel/lib/lio_sam" / meta["imu_node"], "binary_sha1"),
                                  (ROOT / "liosam_ws/devel/lib/lio_sam/lio_sam_mapOptmization", "mapping_binary_sha1"),
                                  (ROOT / meta["launch_file"], "launch_sha1")):
                    require(sha1(path) == meta[key], f"fingerprint: {name}/{key}")
                require(meta["container_image_id"] == manifest["image_id"], f"image: {name}")
                completed = run / "campaign_completion.json"
                if completed.exists():
                    require(json.loads(completed.read_text())["returncode"] == 0, f"runner: {name}")
                s = gate.read_csv(run / "state_log.csv")
                o = gate.read_csv(run / "odometry.csv")
                require(s and o and {r["variant"] for r in s} == {variant}, f"state variant: {name}")
                numeric = pd.DataFrame(s).drop(columns="variant").astype(float).to_numpy()
                require(np.isfinite(numeric).all(), f"nonfinite state: {name}")
                pose = pd.DataFrame(o)[[f"field.pose.pose.{group}.{axis}" for group, axes in (("position", "xyz"), ("orientation", "xyzw")) for axis in axes]].astype(float)
                require(np.isfinite(pose.to_numpy()).all(), f"nonfinite odometry: {name}")
                g = np.array([gate.vector(r, ("gx", "gy", "gz")) for r in s])
                require(np.max(np.abs(np.linalg.norm(g, axis=1) - gravity_norm)) < 1e-10, f"gravity norm: {name}")
                span = gate.gravity_span(s)
                require(span <= 1e-9 if variant == "FG-BA" else span >= 1e-3, f"gravity structure: {name}")
                require(gate.max_departure(s, ("bax", "bay", "baz")) >= 1e-6, f"ba structure: {name}")
                require(gate.max_departure(s, ("bgx", "bgy", "bgz")) >= 1e-7, f"bg structure: {name}")
                launch = (run / "launch.log").read_text(errors="replace")
                markers = {marker: launch.count(marker) for marker in gate.FATAL_MARKERS if marker in launch}
                state_times = [r["timestamp"] for r in s]
                odom_times = [r["%time"] for r in o]
                direction = run / "gravity_direction.csv"
                d = gate.read_csv(direction) if direction.exists() else []
                issues = []
                if markers:
                    issues.append("stability_reset")
                if state_times != st:
                    issues.append("state_timestamps")
                if odom_times != ot:
                    issues.append("odometry_timestamps")
                if len(s) != 1498 or len(o) != 1499:
                    issues.append("frame_count")
                if level == "off":
                    require(not d, f"disabled factor logged: {name}")
                else:
                    if len(d) != len(s):
                        issues.append("factor_state_count")
                    require([int(r["factor_index"]) for r in d] == list(range(1, len(d) + 1)), f"factor index: {name}")
                    values = np.array([[float(r[k]) for k in ("measurement_age_s", "pre_residual_deg", "post_residual_deg")] for r in d])
                    require(np.isfinite(values).all() and values[:, 0].min() >= -1e-9 and values[:, 0].max() <= .05, f"factor instrumentation: {name}")
                    if not markers:
                        require(np.median(values[:, 1]) <= 30 and values[:, 1].max() <= 90, f"factor frame: {name}")
                        require(values[0, 2] <= values[0, 1] and np.median(values[:, 2]) <= 1.05 * np.median(values[:, 1]), f"factor pull: {name}")
                record = {"path": str(run.relative_to(ROOT)), "issues": issues, "fatal_markers": markers,
                          "state_rows": len(s), "odometry_rows": len(o), "factor_rows": len(d),
                          "state_time_mismatches": sum(a != b for a, b in zip(state_times, st)) + abs(len(s) - len(st)),
                          "odometry_time_mismatches": sum(a != b for a, b in zip(odom_times, ot)) + abs(len(o) - len(ot)),
                          "sleep": batch.sleep_audit(run),
                          "sha1": {p.name: sha1(p) for p in run.iterdir() if p.is_file()}}
                if not issues:
                    record.update(status="admitted_accuracy", metrics=evaluate_run(run, "m2dgr", gt_time, gt_position))
                elif name == FAILED:
                    require(markers == {"Large velocity": 56} and odom_times == ot, "known failure changed; audit again")
                    require(set(state_times) <= set(st), "foreign correction time in reset run")
                    record.update(status="observed_estimator_failure_not_accuracy_run", missing_state_rows=len(set(st) - set(state_times)),
                                  factors_without_accepted_state=len({r["timestamp"] for r in d} - set(state_times)))
                elif name == PHASE:
                    require(not markers and len(s) == 1498 and len(o) == 1499 and record["state_time_mismatches"] == record["odometry_time_mismatches"] == 37, "unexpected phase failure")
                    record["status"] = "instrument_timestamp_mismatch_not_accuracy_run"
                else:
                    raise RuntimeError(f"new unreviewed issue in {name}: {issues}")
                cells[name] = record
    return {"audited_at": now(), "cells": cells,
            "interpretation": "A reset is an observed stability outcome, not proof that the factor alone caused it; low-level IMU receipt timing was not recorded. Timestamp-mismatched runs remain excluded by the original zero-tolerance rule."}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive-phase", action="store_true")
    args = parser.parse_args()
    report = inspect()
    manifest = json.loads((CAMPAIGN / "liosam_manifest.json").read_text())
    bag = "data/m2dgr/degraded/hall05_drop5x20.bag"
    require(sha1(ROOT / bag) == manifest["inputs"][bag]["sha1"], "input content changed")
    report["input_bag_sha1"] = manifest["inputs"][bag]["sha1"]
    events = subprocess.check_output(["docker", "events", "--since", "2026-08-31T16:43:00+08:00",
                                      "--until", "2026-08-31T19:30:00+08:00", "--format", "{{json .}}"], text=True)
    running = set()
    timeline = []
    for line in events.splitlines():
        event = json.loads(line)
        if event.get("Type") != "container" or event.get("Action") not in ("start", "die", "oom", "kill"):
            continue
        action, actor = event["Action"], event["Actor"]
        if action == "start":
            running.add(actor["ID"])
            require(len(running) == 1, "overlapping containers in campaign interval")
        elif action == "die":
            require(actor["Attributes"].get("exitCode") == "0", "container failed")
            running.discard(actor["ID"])
        else:
            raise RuntimeError(f"unexpected container event: {action}")
        timeline.append(event)
    require(len([e for e in timeline if e["Action"] == "start"]) == 12 and not running, "incomplete container history")
    report["serial_container_events"] = timeline
    if args.archive_phase:
        require(not subprocess.check_output(["docker", "ps", "-q"], text=True).strip(), "container still active")
        require(not (ROOT / ".chain.lock").exists() and not (ROOT / ".run.lock").exists(), "queue still active")
        require(report["cells"][PHASE]["status"].startswith("instrument_"), "phase output does not need replacement")
        require(not PHASE_ARCHIVE.exists(), "phase archive already exists")
        PHASE_ARCHIVE.mkdir(parents=True)
        write_json(PHASE_ARCHIVE / "audit.json", report)
        (GRID / PHASE).rename(PHASE_ARCHIVE / "FG-BA_s0p5")
        (CAMPAIGN / "console_liosam_weights_hall05_r3_FG-BA_s0p5.log").rename(PHASE_ARCHIVE / "console.log")
        for name in ("supervisor_status.json", "liosam_status.json", "supervisor.out.log", "supervisor.err.log"):
            shutil.copy2(CAMPAIGN / name, PHASE_ARCHIVE / name)
    write_json(ROOT / "report/strengthening_hall_audit_20260831.json", report)
    for name, cell in report["cells"].items():
        print(name, cell["status"], cell["issues"])


if __name__ == "__main__":
    main()
