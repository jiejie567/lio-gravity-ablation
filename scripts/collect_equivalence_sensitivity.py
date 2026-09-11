#!/usr/bin/env python3
"""Generate scale-aware sensitivity checks for the nominal FixG comparison.

This analysis does not add experimental units. It re-expresses the admitted
Online/FixG pairs from summary.json using the pre-specified 5% TOST margin, a
stricter post-hoc 2% sensitivity margin, absolute differences, and an
equal-weight trajectory-family sensitivity check. The independent
launch-specific reproduction is read from strengthening_20260831.json.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy import stats


ROOT = Path(__file__).resolve().parent.parent
SUMMARY_PATH = ROOT / "report" / "summary.json"
STRENGTHENING_PATH = ROOT / "report" / "strengthening_20260831.json"
OUTPUT_PATH = ROOT / "report" / "equivalence_sensitivity.json"

CORE = [
    "ntu_day_01_os1",
    "ntu_day_02_os1",
    "ntu_day_10_os1",
    "ntu_night_04_os1",
    "ntu_night_13_os1",
    "kth_day_10_os1",
    "kth_night_05_os1",
    "tuhh_day_02_os1",
    "tuhh_day_04_os1",
    "tuhh_night_09_os1",
    "IndoorOffice1",
    "hall_05_run",
]
FAMILIES = {
    "NTU": CORE[0:5],
    "KTH": CORE[5:7],
    "TUHH": CORE[7:10],
    "TIERS": [CORE[10]],
    "M2DGR": [CORE[11]],
}
METRICS = ("rmse_z_m", "ate_rmse_m")
FORMAL_MARGIN = 0.05
SENSITIVITY_MARGIN = 0.02


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tost(ratios: np.ndarray, margin: float) -> float:
    log_ratios = np.log(ratios)
    delta = math.log1p(margin)
    return float(max(
        stats.ttest_1samp(log_ratios, -delta, alternative="greater").pvalue,
        stats.ttest_1samp(log_ratios, delta, alternative="less").pvalue,
    ))


def summarize(ratios: np.ndarray) -> dict[str, object]:
    log_ratios = np.log(ratios)
    half = float(stats.t.ppf(0.95, len(log_ratios) - 1)
                 * stats.sem(log_ratios))
    mean = float(log_ratios.mean())
    lo, center, hi = 100 * (np.exp([mean - half, mean, mean + half]) - 1)
    return {
        "n_sequence_units": int(len(ratios)),
        "mean_paired_effect_pct": float(center),
        "ci90_pct": [float(lo), float(hi)],
        "formal_5pct_tost_p": tost(ratios, FORMAL_MARGIN),
        "posthoc_2pct_tost_p": tost(ratios, SENSITIVITY_MARGIN),
    }


def main() -> None:
    summary = json.loads(SUMMARY_PATH.read_text())
    strengthening = json.loads(STRENGTHENING_PATH.read_text())
    sequences = summary["sequences"]

    primary: dict[str, object] = {}
    for metric in METRICS:
        ratios = np.asarray([
            sequences[name]["runs"]["RED21"][metric]
            / sequences[name]["runs"]["A"][metric]
            for name in CORE
        ], dtype=float)
        differences = np.asarray([
            sequences[name]["runs"]["RED21"][metric]
            - sequences[name]["runs"]["A"][metric]
            for name in CORE
        ], dtype=float)
        record = summarize(ratios)
        record["absolute_difference_m"] = {
            "median": float(np.median(np.abs(differences))),
            "signed_range": [float(differences.min()), float(differences.max())],
        }
        primary[metric] = record

    reproduction_runs = strengthening["fastlio_reproduction"]["sequences"]
    reproduction: dict[str, object] = {}
    for metric in METRICS:
        ratios = np.asarray([
            entry["metrics"][metric]["runs"]["RED21"]["new_m"]
            / entry["metrics"][metric]["runs"]["A"]["new_m"]
            for entry in reproduction_runs
        ], dtype=float)
        reproduction[metric] = summarize(ratios)

    family_balanced: dict[str, object] = {}
    for metric in METRICS:
        family_log_ratios = []
        family_effects = {}
        for family, names in FAMILIES.items():
            ratios = np.asarray([
                sequences[name]["runs"]["RED21"][metric]
                / sequences[name]["runs"]["A"][metric]
                for name in names
            ], dtype=float)
            mean_log_ratio = float(np.log(ratios).mean())
            family_log_ratios.append(mean_log_ratio)
            family_effects[family] = float(100 * math.expm1(mean_log_ratio))
        family_ratios = np.exp(np.asarray(family_log_ratios))
        record = summarize(family_ratios)
        record["family_effect_pct"] = family_effects
        family_balanced[metric] = record

    hall = sequences["hall_05_run"]["runs"]
    hall_example = {}
    for metric in METRICS:
        online = float(hall["A"][metric])
        fixg = float(hall["RED21"][metric])
        hall_example[metric] = {
            "online_m": online,
            "fixg_m": fixg,
            "difference_m": fixg - online,
            "difference_mm": 1000 * (fixg - online),
            "relative_pct": 100 * (fixg / online - 1),
        }

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete_existing_results_only",
        "scope": (
            "Sensitivity analysis of the same 12 admitted sequence units; "
            "not additional experiments or independent samples."
        ),
        "source_sha256": {
            "summary_json": sha256(SUMMARY_PATH),
            "strengthening_json": sha256(STRENGTHENING_PATH),
        },
        "margins": {
            "formal_pre_specified_pct": 100 * FORMAL_MARGIN,
            "posthoc_sensitivity_pct": 100 * SENSITIVITY_MARGIN,
            "log_ratio_lower_definition": "1 / (1 + margin)",
            "log_ratio_upper_definition": "1 + margin",
        },
        "primary": primary,
        "launch_specific_reproduction": reproduction,
        "trajectory_family_balanced": {
            "families": FAMILIES,
            "method": "mean log ratio within family, then equal weight across families",
            "metrics": family_balanced,
        },
        "small_baseline_example": {
            "sequence": "hall_05_run",
            "metrics": hall_example,
        },
    }
    OUTPUT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
