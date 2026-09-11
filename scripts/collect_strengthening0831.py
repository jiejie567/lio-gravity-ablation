#!/usr/bin/env python3
"""Collect all admitted strengthening runs without replacing manuscript claims.

FAST-LIO metrics are produced by the existing unified collector and retained
in summary.json under distinct run names. The new report compares old/new
results and keeps LIO-SAM sequence and repeat units separate.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import subprocess
import sys

import numpy as np
from scipy import stats

from batch_fastlio_repro0831 import ROOT, CAMPAIGN, SEQUENCES, SUFFIX, now, require, write_json
from batch_liosam_strengthening0831 import HOLDOUTS, LEVELS, VARIANTS, WEIGHTS

METRICS = ("rmse_z_m", "ate_rmse_m")


def read(path):
    return json.loads(path.read_text())


def interval(values):
    return {"values": values, "median": float(np.median(values)), "range": [float(min(values)), float(max(values))]}


def equivalence(ratios):
    """Keep the existing make_tables.py symmetric log-ratio TOST protocol."""
    log_ratio = np.log(np.asarray(ratios))
    bound = math.log(1.05)
    half = stats.t.ppf(0.95, len(log_ratio) - 1) * stats.sem(log_ratio)
    p = max(stats.ttest_1samp(log_ratio, -bound, alternative="greater").pvalue,
            stats.ttest_1samp(log_ratio, bound, alternative="less").pvalue)
    return {"sequence_units": len(ratios), "ratio_band": [1 / 1.05, 1.05],
            "mean_paired_effect_pct": float(100 * np.expm1(log_ratio.mean())),
            "ci90_pct": (100 * np.expm1([log_ratio.mean() - half, log_ratio.mean() + half])).tolist(),
            "tost_p": float(p), "equivalent_at_alpha_0p05": bool(p < 0.05)}


def fastlio_results():
    for seq in SEQUENCES:
        require(read(CAMPAIGN / f"validation_{seq}.json")["passed"], f"unvalidated FAST-LIO pair: {seq}")
    command = [sys.executable, str(ROOT / "scripts/collect_metrics.py"), "--only", *SEQUENCES]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    (CAMPAIGN / "collect_metrics.log").write_text(completed.stdout + completed.stderr)
    # The legacy collection includes known excluded runs. Do not ignore any
    # new failure, and expose the complete collector diagnostics in the report.
    require(completed.returncode in (0, 1), "unified collector crashed")
    require(not any(SUFFIX in line for line in completed.stdout.splitlines() if line.startswith("[fail]")), "new reproduction run failed the unified collector")
    summary = read(ROOT / "report/summary.json")["sequences"]
    old = read(CAMPAIGN / "summary_before.json")["sequences"]
    sequences = []
    for seq in SEQUENCES:
        runs = summary[seq]["runs"]
        pairs = {}
        for metric in METRICS:
            values = {}
            for method in ("A", "RED21"):
                record = runs[method + SUFFIX]
                require(record.get("usable", True) and not record.get("frames_mismatch"), f"unusable new run: {seq}/{method}")
                require(np.isfinite(record[metric]), f"nonfinite result: {seq}/{method}/{metric}")
                values[method] = {"old_m": old[seq]["runs"][method][metric], "new_m": record[metric],
                                  "old_to_new_change_pct": 100 * (record[metric] / old[seq]["runs"][method][metric] - 1)}
            pairs[metric] = {"runs": values,
                            "old_fixg_effect_pct": 100 * (values["RED21"]["old_m"] / values["A"]["old_m"] - 1),
                            "new_fixg_effect_pct": 100 * (values["RED21"]["new_m"] / values["A"]["new_m"] - 1),
                            "new_fixg_difference_m": values["RED21"]["new_m"] - values["A"]["new_m"]}
        sequences.append({"sequence": seq, "metrics": pairs})
    population = {}
    for metric in METRICS:
        population[metric] = {
            age: equivalence([item["metrics"][metric]["runs"]["RED21"][age + "_m"] / item["metrics"][metric]["runs"]["A"][age + "_m"] for item in sequences])
            for age in ("old", "new")
        }
    return {"sequences": sequences, "population": population,
            "collector_returncode": completed.returncode,
            "collector_failures": [line for line in completed.stdout.splitlines() if line.startswith("[fail]")],
            "inference": "12 paired sequence units; reproduction is not 12 additional independent sequences"}


def weight_results():
    sequences = []
    for dataset in WEIGHTS:
        repeats = []
        for repeat in (1, 2, 3):
            grid = CAMPAIGN / "liosam_weights" / dataset / f"r{repeat}"
            require(read(grid / "validation.json")["passed"], f"unvalidated direction sweep: {grid}")
            repeats.append(read(grid / "metrics.json"))
        cells = {}
        for variant in VARIANTS:
            for level in LEVELS:
                name = f"{variant}_{level}"
                cell = {"runs": [r["runs"][name] for r in repeats]}
                for metric, label in (("rmse_z_m", "rmse_z"), ("ate_rmse_m", "ate")):
                    cell[metric] = interval([r["runs"][name][metric] for r in repeats])
                    for unit in ("m", "pct"):
                        key = f"delta_{label}_{unit}_vs_off"
                        cell[key] = interval([r["runs"][name][key] for r in repeats])
                cells[name] = cell
        sequences.append({"sequence": dataset, "paired_repeats": 3, "cells": cells})
    return {"sequences": sequences,
            "inference": "Within-sequence paired repeat ranges; no cross-trajectory pooling; reused controls remain explicitly listed in the manifest"}


def holdout_results():
    sequences = []
    for seq in HOLDOUTS:
        grid = CAMPAIGN / "liosam_holdout" / seq
        require(read(grid / "validation.json")["passed"], f"unvalidated new LIO-SAM sequence: {seq}")
        sequences.append(read(grid / "metrics.json"))
    original = read(CAMPAIGN / "liosam_full_before.json")["sequences"]
    return {"new_sequences": sequences, "previous_sequences": original,
            "total_sequence_units": len(original) + len(sequences),
            "inference": "Descriptive cross-estimator evidence only; no automatic equivalence inference from four sequences"}


def main():
    require(read(CAMPAIGN / "fastlio_status.json")["status"] == "runs_validated_analysis_pending", "FAST-LIO campaign is not complete")
    require(read(CAMPAIGN / "liosam_status.json")["status"] == "runs_validated", "LIO-SAM campaign is not complete")
    write_json(CAMPAIGN / "collection_status.json", {"status": "collecting", "started_at": now()})
    result = {"created_at": now(), "status": "all_prescribed_runs_validated",
              "fastlio_reproduction": fastlio_results(),
              "liosam_dropout_weights": weight_results(),
              "liosam_new_sequences": holdout_results(),
              "scope": "No continuously available outage-time direction factor was implemented; no manuscript claim was automatically changed."}
    output = ROOT / "report/strengthening_20260831.json"
    write_json(output, result)
    lines = ["# 2026-08-31 补强实验结果（机器生成）", "", "原始结果和逐格指标见 `strengthening_20260831.json`。未自动修改论文主张。", "", "## FAST-LIO2 新旧主结论", "", "| 指标 | 新配对平均变化 | 90% CI | TOST p |", "|---|---:|---:|---:|"]
    for metric in METRICS:
        value = result["fastlio_reproduction"]["population"][metric]["new"]
        lines.append(f"| {metric} | {value['mean_paired_effect_pct']:+.3f}% | {value['ci90_pct'][0]:+.3f}% 至 {value['ci90_pct'][1]:+.3f}% | {value['tost_p']:.4g} |")
    lines += ["", "## LIO-SAM 5 s 断测：因子相对 off 的配对中位变化", "", "| 序列 | 状态 | 权重 | RMSE_z | ATE |", "|---|---|---|---:|---:|"]
    for seq in result["liosam_dropout_weights"]["sequences"]:
        for variant in VARIANTS:
            for level in ("s0p5", "s2", "s5"):
                cell = seq["cells"][f"{variant}_{level}"]
                lines.append(f"| {seq['sequence']} | {variant} | {level} | {cell['delta_rmse_z_pct_vs_off']['median']:+.2f}% | {cell['delta_ate_pct_vs_off']['median']:+.2f}% |")
    lines += ["", "## LIO-SAM 新序列：绝对误差", "", "| 序列 | 状态 | RMSE_z [m] | ATE [m] |", "|---|---|---:|---:|"]
    for seq in result["liosam_new_sequences"]["new_sequences"]:
        for variant, value in seq["runs"].items():
            lines.append(f"| {seq['sequence']} | {variant} | {value['rmse_z_m']:.5f} | {value['ate_rmse_m']:.5f} |")
    (ROOT / "report/STRENGTHENING_RESULTS_20260831.md").write_text("\n".join(lines) + "\n")
    write_json(CAMPAIGN / "collection_status.json", {"status": "complete", "finished_at": now(), "report": str(output.relative_to(ROOT))})
    print(f"ALL STRENGTHENING RUNS COLLECTED: {output}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:
        write_json(CAMPAIGN / "collection_status.json", {"status": "stopped_for_audit", "error": str(exc), "at": now()})
        raise
