#!/usr/bin/env python3
"""Resume only prescribed unfinished cells after the documented Hall05 audit."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

import numpy as np

import batch_liosam_strengthening0831 as batch
from audit_liosam_hall0831 import FAILED, GRID, PHASE, PHASE_ARCHIVE, inspect
from batch_fastlio_repro0831 import ROOT, CAMPAIGN, now, require, sha1, write_json
import audit_liosam_tuhh0831 as tuhh_audit


def audited_holdouts(manifest):
    """Run holdouts while treating method arc excursions as outcomes, not bad GT."""
    for seq, config in batch.HOLDOUTS.items():
        # Independent FAST-LIO pairs already establish that this GT moves with
        # the platform and has a valid arc-length scale.
        fast_gate = json.loads((CAMPAIGN / f"validation_{seq}_os1.json").read_text())
        require(fast_gate["passed"] and all(0.6 <= run["arc_ratio"] <= 1.6 for run in fast_gate["runs"].values()), f"independent GT gate failed: {seq}")
        grid = CAMPAIGN / "liosam_holdout" / seq
        for variant in batch.STATE_VARIANTS:
            run = grid / variant
            command = ["bash", "scripts/run_liosam_mcd_ablation.sh", variant, config["setup"],
                       f"data/mcd/{seq}/os1.bag", f"data/mcd/{seq}/{config['imu']}.bag",
                       str(run.relative_to(ROOT)), "0", config["duration"], "0.25"]
            batch.run_one(command, run, manifest)
        structural = subprocess.run([sys.executable, str(ROOT / "scripts/validate_liosam_ablation.py"), str(grid)],
                                    text=True, capture_output=True)
        (grid / "validation.log").write_text(structural.stdout + structural.stderr)
        require(structural.returncode == 0, f"held-out structural gate failed: {grid}")
        gt_path = ROOT / f"data/mcd/{seq}/gt/pose_inW.csv"
        gt_time, gt_position = batch.load_gt(gt_path)
        reference_times = [r["%time"] for r in batch.rows(grid / "FG-BA/odometry.csv")]
        arcs, warnings = {}, []
        for variant in batch.STATE_VARIANTS:
            run = grid / variant
            require([r["%time"] for r in batch.rows(run / "odometry.csv")] == reference_times, f"{seq}: exact odometry timestamps differ")
            time, positions = batch.load_estimate(run / "odometry.csv", config["setup"])
            require(np.isfinite(time).all() and np.isfinite(positions).all(), f"{seq}/{variant}: nonfinite odometry")
            valid = (time >= gt_time[0]) & (time <= gt_time[-1])
            require(valid.sum() > 10, f"{seq}: insufficient GT overlap")
            time, positions = time[valid], positions[valid]
            truth = np.column_stack([np.interp(time, gt_time, gt_position[:, axis]) for axis in range(3)])
            ratio = float(np.linalg.norm(np.diff(positions, axis=0), axis=1).sum() /
                          np.linalg.norm(np.diff(truth, axis=0), axis=1).sum())
            require(np.isfinite(ratio), f"{seq}/{variant}: nonfinite arc ratio")
            require(time[-1] - time[0] >= 0.97 * (gt_time[-1] - gt_time[0]), f"{seq}: truncated trajectory")
            arcs[variant] = ratio
            if not 0.6 <= ratio <= 1.6:
                warnings.append({"variant": variant, "estimate_to_gt_arc_ratio": ratio,
                                 "status": tuhh_audit.ARC_WARNING})
            require(batch.sleep_audit(run)["events"] == 0, f"sleep contaminated: {run}")
        subprocess.run([sys.executable, str(ROOT / "scripts/collect_liosam_mcd_full.py"), str(grid),
                        config["setup"], seq, str(gt_path), str(grid / "metrics.json")],
                       check=True, stdout=subprocess.DEVNULL)
        write_json(grid / "validation.json", {"passed": True, "validated_at": now(),
                   "gt_validated_by": f"validation_{seq}_os1.json", "arc_ratios": arcs,
                   "arc_warnings": warnings,
                   "policy": "complete finite estimator arc excursions retain their accuracy metrics"})
        print(f"HOLDOUT GATE PASS {seq}: arc warnings={warnings}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--after-tuhh-audit", action="store_true")
    args = parser.parse_args()
    manifest = json.loads((CAMPAIGN / "liosam_manifest.json").read_text())
    batch.fingerprint_gate(manifest)
    audit = json.loads((PHASE_ARCHIVE / "audit.json").read_text())
    # The reset outcome is immutable and is never resubmitted. Only the
    # separately audited, timestamp-mismatched run has been archived.
    for name, cell in audit["cells"].items():
        if name == PHASE:
            continue
        for filename, digest in cell["sha1"].items():
            require(sha1(GRID / name / filename) == digest, f"audited output changed: {name}/{filename}")
    if args.after_tuhh_audit:
        followup = json.loads((tuhh_audit.FOLLOWUP / "audit.json").read_text())
        for report in followup["rounds"].values():
            for cell in report["cells"].values():
                for filename, digest in cell["sha1"].items():
                    require(sha1(ROOT / cell["path"] / filename) == digest, f"audited TUHH output changed: {cell['path']}/{filename}")
        resume = json.loads((tuhh_audit.FOLLOWUP / "resume_source.json").read_text())
        for relative, digest in resume["sha1"].items():
            require(sha1(ROOT / relative) == digest, f"resume source changed: {relative}")
    lock = ROOT / ".chain.lock"
    lock.mkdir()
    (lock / "pid").write_text(str(os.getpid()) + "\n")
    (lock / "what").write_text("LIO-SAM prescribed remainder after Hall05 audit\n")
    status = {"status": "running", "started_at": now(), "pid": os.getpid(),
              "preserved_failure": str((GRID / FAILED).relative_to(ROOT)),
              "scope": ("14 remaining TUHH dropout runs and eight held-out runs; preserve Hall reset and TUHH arc failure"
                        if args.after_tuhh_audit else "one instrument-only replacement, 18 TUHH dropout runs, eight held-out runs")}
    write_json(CAMPAIGN / "liosam_remaining_status.json", status)
    try:
        require(not (ROOT / ".run.lock").exists(), "another experiment is active")
        config = batch.WEIGHTS["hall05"]
        repaired = GRID / PHASE
        command = ["bash", "scripts/run_liosam_gravity_direction.sh", "FG-BA", config["bag"],
                   str(repaired.relative_to(ROOT)), str(batch.LEVELS["s0p5"]), "0", config["duration"], config["rate"]]
        batch.run_one(command, repaired, manifest)
        hall = inspect()
        require(hall["cells"][PHASE]["status"] == "admitted_accuracy", "replacement still fails the original timestamp gate")
        require(hall["cells"][FAILED]["status"] == "observed_estimator_failure_not_accuracy_run", "reset outcome changed")
        result = subprocess.run([sys.executable, str(ROOT / "scripts/validate_liosam_direction_sweep.py"),
                                 str(GRID / "r3"), "--levels", "off,s0p5,s2"], capture_output=True, text=True)
        (GRID / "r3/validation_no_s5.log").write_text(result.stdout + result.stderr)
        require(result.returncode == 0, "Hall05 non-failure subset did not pass the unchanged validator")
        write_json(GRID / "r3/audited_outcomes.json", hall)
        print("HALL AUDIT COMPLETE: reset retained, timestamp-only replacement passed", flush=True)

        dataset = "tuhh_day04"
        config = batch.WEIGHTS[dataset]
        for repeat in (1, 2, 3):
            grid = CAMPAIGN / "liosam_weights" / dataset / f"r{repeat}"
            grid.mkdir(parents=True, exist_ok=True)
            levels = ("off", "s2", "s0p5", "s5") if repeat != 2 else ("off", "s2", "s5", "s0p5")
            for variant in batch.VARIANTS:
                for level in levels:
                    run = grid / f"{variant}_{level}"
                    reference = batch.reused_control(dataset, variant, level, repeat)
                    if reference is not None:
                        frozen = manifest["reused_controls"][str(reference.relative_to(ROOT))]
                        for name, digest in frozen["sha1"].items():
                            require(sha1(reference / name) == digest, f"reused output changed: {reference / name}")
                        if not run.exists():
                            run.symlink_to(reference, target_is_directory=True)
                        require(run.resolve() == reference.resolve(), f"wrong reused control: {run}")
                        continue
                    command = ["bash", "scripts/run_liosam_mcd_gravity_direction.sh", variant, "handheld",
                               config["bag"], config["imu"], str(run.relative_to(ROOT)), str(batch.LEVELS[level]),
                               "0", config["duration"], config["rate"]]
                    batch.run_one(command, run, manifest)
            if args.after_tuhh_audit:
                outcomes = tuhh_audit.inspect_round(grid)
                write_json(grid / "audited_outcomes.json", outcomes)
                failures = [name for name, cell in outcomes["cells"].items() if cell["status"] != "admitted_accuracy"]
                print(f"TUHH ROUND AUDITED {repeat}: preserved arc failures={failures}", flush=True)
            else:
                batch.validate_weights(grid, config)  # No new failure is automatically waived.
        audited_holdouts(manifest) if args.after_tuhh_audit else batch.holdouts(manifest)
        status.update(status="complete_with_preserved_failure", finished_at=now())
        write_json(CAMPAIGN / "liosam_status.json", {"status": "completed_with_audited_failure", "finished_at": now(), "failure": status["preserved_failure"]})
    except BaseException as exc:
        status.update(status="stopped_for_audit", error=str(exc), finished_at=now())
        raise
    finally:
        write_json(CAMPAIGN / "liosam_remaining_status.json", status)
        (lock / "pid").unlink()
        (lock / "what").unlink()
        lock.rmdir()


if __name__ == "__main__":
    main()
