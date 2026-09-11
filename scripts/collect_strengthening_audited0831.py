#!/usr/bin/env python3
"""Keep observed failures and report accuracy only for strictly admitted runs."""
from __future__ import annotations

import argparse
import json

import batch_liosam_strengthening0831 as batch
import collect_strengthening0831 as original
from audit_liosam_hall0831 import FAILED, PHASE_ARCHIVE, inspect
from batch_fastlio_repro0831 import ROOT, CAMPAIGN, now, require, write_json
import audit_liosam_tuhh0831 as tuhh_audit


def weight_results(hall, tuhh=None):
    sequences = []
    for dataset in batch.WEIGHTS:
        repeats = []
        for repeat in (1, 2, 3):
            if dataset == "hall05":
                runs = {f"{v}_{l}": hall["cells"][f"r{repeat}/{v}_{l}"] for v in batch.VARIANTS for l in batch.LEVELS}
            elif tuhh is not None:
                runs = tuhh[repeat]["cells"]
            else:
                grid = CAMPAIGN / "liosam_weights" / dataset / f"r{repeat}"
                require(original.read(grid / "validation.json")["passed"], f"unvalidated TUHH repeat {repeat}")
                runs = {name: {"status": "admitted_accuracy", "metrics": value}
                        for name, value in original.read(grid / "metrics.json")["runs"].items()}
            repeats.append(runs)
        cells = {}
        for variant in batch.VARIANTS:
            for level in batch.LEVELS:
                name = f"{variant}_{level}"
                valid, failures = [], []
                for repeat, runs in enumerate(repeats, 1):
                    record = runs[name]
                    if record["status"] in ("admitted_accuracy", tuhh_audit.ARC_WARNING):
                        metrics = dict(record["metrics"])
                        baseline = runs[f"{variant}_off"]["metrics"]
                        for metric, label in (("rmse_z_m", "rmse_z"), ("ate_rmse_m", "ate")):
                            delta = metrics[metric] - baseline[metric]
                            metrics[f"delta_{label}_m_vs_off"] = delta
                            metrics[f"delta_{label}_pct_vs_off"] = 100 * delta / baseline[metric]
                        valid.append({"repeat": repeat, "metrics": metrics,
                                      "arc_warning": record["status"] == tuhh_audit.ARC_WARNING})
                    else:
                        hall_reset = dataset == "hall05" and f"r{repeat}/{name}" == FAILED and record["status"] == "observed_estimator_failure_not_accuracy_run"
                        require(hall_reset, "unreviewed exclusion")
                        failures.append({"repeat": repeat, **record})
                cell = {"requested_repeats": len(repeats), "accuracy_repeats": len(valid), "failed_repeats": len(failures),
                        "arc_warning_repeats": sum(run.get("arc_warning", False) for run in valid),
                        "successful_runs": valid, "failures": failures,
                        "accuracy_scope": "conditional on strict admission; failures are not zero error and are not omitted from outcome counts"}
                for metric, label in (("rmse_z_m", "rmse_z"), ("ate_rmse_m", "ate")):
                    cell[metric] = original.interval([r["metrics"][metric] for r in valid]) if valid else None
                    for unit in ("m", "pct"):
                        key = f"delta_{label}_{unit}_vs_off"
                        cell[key] = original.interval([r["metrics"][key] for r in valid]) if valid else None
                cells[name] = cell
        sequences.append({"sequence": dataset, "cells": cells})
    return {"sequences": sequences, "inference": "Per-trajectory repeat outcomes; no pooled equivalence test and no accuracy-only replacement of a failed repeat"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--after-tuhh-audit", action="store_true")
    args = parser.parse_args()
    require(original.read(CAMPAIGN / "liosam_remaining_status.json")["status"] == "complete_with_preserved_failure", "remaining campaign is incomplete")
    require(original.read(CAMPAIGN / "fastlio_status.json")["status"] == "runs_validated_analysis_pending", "FAST-LIO campaign is incomplete")
    write_json(CAMPAIGN / "collection_status.json", {"status": "collecting", "started_at": now()})
    hall = inspect()
    tuhh = {r: tuhh_audit.inspect_round(CAMPAIGN / f"liosam_weights/tuhh_day04/r{r}") for r in (1, 2, 3)} if args.after_tuhh_audit else None
    result = {"created_at": now(), "status": "completed_with_documented_failed_outcomes",
              "fastlio_reproduction": original.fastlio_results(), "liosam_dropout_weights": weight_results(hall, tuhh),
              "liosam_new_sequences": original.holdout_results(),
              "technical_exclusions": [original.read(CAMPAIGN / "interruption_audit.json"), original.read(PHASE_ARCHIVE / "audit.json")],
              "scope": "The Hall05 reset is a failed outcome with no accuracy value. Reviewed TUHH excessive-arc outcomes are complete finite trajectories and retain accuracy values with warnings. No outcome was replaced and trajectories are not pooled."}
    if args.after_tuhh_audit:
        result["reviewed_arc_outcome"] = original.read(tuhh_audit.FOLLOWUP / "audit.json")
    write_json(ROOT / "report/strengthening_20260831.json", result)
    lines = ["# 补强实验结果（含失败结局，机器生成）", "", "## FAST-LIO2：12 条序列的配对复现", "",
             "| 指标 | 新配对均值变化 | 90% CI | TOST p |", "|---|---:|---:|---:|"]
    for metric in original.METRICS:
        value = result["fastlio_reproduction"]["population"][metric]["new"]
        lines.append(f"| {metric} | {value['mean_paired_effect_pct']:+.3f}% | {value['ci90_pct'][0]:+.3f}% 至 {value['ci90_pct'][1]:+.3f}% | {value['tost_p']:.4g} |")
    lines += ["", "## LIO-SAM：方向因子相对 off", "", "准确度范围只描述通过闸门的运行；失败次数必须同时阅读。不同轨迹不合并统计。", "",
              "| 序列 | 状态/权重 | 精度/计划 | 重置/失效 | 弧长警报 | RMSE_z 中位变化 | ATE 中位变化 |", "|---|---|---:|---:|---:|---:|---:|"]
    for seq in result["liosam_dropout_weights"]["sequences"]:
        for name, cell in seq["cells"].items():
            if name.endswith("_off"):
                continue
            z = cell["delta_rmse_z_pct_vs_off"]
            ate = cell["delta_ate_pct_vs_off"]
            z_text = f"{z['median']:+.2f}%" if z is not None else "—"
            ate_text = f"{ate['median']:+.2f}%" if ate is not None else "—"
            lines.append(f"| {seq['sequence']} | {name} | {cell['accuracy_repeats']}/{cell['requested_repeats']} | {cell['failed_repeats']} | {cell['arc_warning_repeats']} | {z_text} | {ate_text} |")
    lines += ["", "Hall05 的重置不生成精度值；TUHH 的弧长越界发生在可用共享 GT 上，完整有限输出保留精度并加警报。两者不混称一种失稳。"]
    lines += ["", "## 新增完整序列", "", "| 序列 | 状态 | RMSE_z [m] | ATE [m] |", "|---|---|---:|---:|"]
    for seq in result["liosam_new_sequences"]["new_sequences"]:
        for variant, value in seq["runs"].items():
            lines.append(f"| {seq['sequence']} | {variant} | {value['rmse_z_m']:.5f} | {value['ate_rmse_m']:.5f} |")
    lines += ["", "原始逐次值、全范围、失败日志与技术排除记录见 `strengthening_20260831.json`。"]
    (ROOT / "report/STRENGTHENING_RESULTS_20260831.md").write_text("\n".join(lines) + "\n")
    write_json(CAMPAIGN / "collection_status.json", {"status": "complete_with_documented_failure", "finished_at": now()})


if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:
        write_json(CAMPAIGN / "collection_status.json", {"status": "stopped_for_audit", "error": str(exc), "at": now()})
        raise
