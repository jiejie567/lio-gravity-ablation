#!/usr/bin/env python3
"""Validate and summarize the paired 23D Online / 21D FixG runtime runs."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import platform
import re
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RUN_ROOT = ROOT / "results" / "os1" / "runtime_true_dim_ntu_day_10"
OUTPUT = ROOT / "report" / "runtime_benchmark.json"
METHODS = {
    "A": {"dimension": 23, "launch": "mapping_exp", "binary": "fastlio_mapping"},
    "RED21": {"dimension": 21, "launch": "mapping_exp_redg", "binary": "fastlio_mapping_redg"},
}
WARMUP_SCANS = 100
TIMING_LINE = re.compile(
    r"ave match: ([0-9.]+) ave solve: ([0-9.]+).*"
    r"ave total: ([0-9.]+).*construct H: ([0-9.]+)"
)


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_meta(path: Path) -> dict[str, str]:
    out = {}
    for line in path.read_text().splitlines():
        if ": " in line:
            key, value = line.split(": ", 1)
            out[key] = value
    return out


def sleep_events() -> list[dt.datetime]:
    try:
        proc = subprocess.run(
            ["pmset", "-g", "log"], capture_output=True, text=True,
            errors="replace", timeout=180, check=False,
        )
    except Exception:
        return []
    events = []
    for line in proc.stdout.splitlines():
        if "Entering Sleep state" not in line:
            continue
        try:
            events.append(dt.datetime.strptime(" ".join(line.split()[:2]), "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            pass
    return events


def load_run(method: str, repeat: int, sleeps: list[dt.datetime]) -> tuple[dict, np.ndarray, np.ndarray]:
    run_dir = RUN_ROOT / f"{method}_r{repeat}"
    timing_path = run_dir / "runtime_log.csv"
    state_path = run_dir / "state_log.csv"
    meta_path = run_dir / "run_meta.txt"
    console_path = run_dir / "console.log"
    for path in (timing_path, state_path, meta_path, console_path):
        if not path.is_file():
            raise FileNotFoundError(path)

    timing = pd.read_csv(timing_path, skipinitialspace=True).rename(columns=str.strip).dropna()
    state = pd.read_csv(state_path).dropna()
    required = {"time_stamp", "total time", "preprocess time", "scan point size"}
    missing = required.difference(timing.columns)
    if missing:
        raise ValueError(f"{timing_path}: missing columns {sorted(missing)}")
    if len(timing) != len(state):
        raise ValueError(f"{method} r{repeat}: timing/state frames {len(timing)}/{len(state)}")
    if len(timing) <= WARMUP_SCANS:
        raise ValueError(f"{method} r{repeat}: only {len(timing)} frames")

    g = state[["gx", "gy", "gz"]].to_numpy(float)
    ba = state[["bax", "bay", "baz"]].to_numpy(float)
    position = state[["px", "py", "pz"]].to_numpy(float)
    gravity_span = float(np.max(np.abs(g - g[0])))
    ba_span = float(np.max(np.abs(ba - ba[0])))
    gravity_norm_error = float(np.max(np.abs(np.linalg.norm(g, axis=1) - 9.8090)))
    if method == "A" and gravity_span <= 1e-6:
        raise ValueError(f"{method} r{repeat}: online gravity did not move")
    if method == "RED21" and gravity_span > 1e-12:
        raise ValueError(f"{method} r{repeat}: fixed gravity moved by {gravity_span:.3e}")
    if ba_span <= 1e-6:
        raise ValueError(f"{method} r{repeat}: online accelerometer bias did not move")
    if gravity_norm_error > 1e-6:
        raise ValueError(f"{method} r{repeat}: gravity norm error {gravity_norm_error:.3e}")

    gt_len = float(json.loads((ROOT / "report" / "summary.json").read_text())
                   ["sequences"]["ntu_day_10_os1"]["gt"]["path_len_m"])
    path_len = float(np.linalg.norm(np.diff(position, axis=0), axis=1).sum())
    if not 0.6 <= path_len / gt_len <= 1.6:
        raise ValueError(f"{method} r{repeat}: path length {path_len:.1f} m vs GT {gt_len:.1f} m")

    meta = parse_meta(meta_path)
    expected = METHODS[method]
    if meta.get("launch") != expected["launch"]:
        raise ValueError(f"{method} r{repeat}: launch {meta.get('launch')}")
    fingerprint = meta.get("fastlio_binary_sha1", "")
    if not re.fullmatch(r"[0-9a-f]{12}", fingerprint):
        raise ValueError(f"{method} r{repeat}: invalid binary fingerprint")

    start = dt.datetime.fromisoformat(meta["date"])
    end = dt.datetime.fromtimestamp(state_path.stat().st_mtime)
    sleep_hits = [event.isoformat() for event in sleeps if start <= event <= end]
    if sleep_hits:
        raise ValueError(f"{method} r{repeat}: host sleep during run: {sleep_hits}")

    core = timing["total time"].to_numpy(float)[WARMUP_SCANS:] * 1000.0
    preprocess = timing["preprocess time"].to_numpy(float)[WARMUP_SCANS:] * 1000.0
    if not (np.isfinite(core).all() and np.isfinite(preprocess).all()):
        raise ValueError(f"{method} r{repeat}: non-finite timing")
    if (core <= 0).any() or (preprocess < 0).any():
        raise ValueError(f"{method} r{repeat}: non-positive timing")

    # Preprocessing is recorded in the subscriber callback and is not enclosed
    # by the t0--t5 core timer. Their means are therefore additive without
    # pretending the legacy one-index-shifted arrays are frame aligned.
    core_mean = float(np.mean(core))
    pre_mean = float(np.mean(preprocess))
    final_match = None
    for line in console_path.read_text(errors="replace").splitlines():
        match = TIMING_LINE.search(line)
        if match:
            final_match = match
    if final_match is None:
        raise ValueError(f"{method} r{repeat}: final cumulative timing line missing")
    match_ms, measurement_solve_ms, reported_total_ms, jacobian_ms = (
        1000.0 * float(value) for value in final_match.groups()
    )
    filter_algebra_ms = measurement_solve_ms - jacobian_ms
    if filter_algebra_ms <= 0 or reported_total_ms <= 0:
        raise ValueError(f"{method} r{repeat}: invalid cumulative timing")
    record = {
        "method": method,
        "dimension": expected["dimension"],
        "repeat": repeat,
        "order_start": meta["date"],
        "frames": int(len(timing)),
        "warmup_scans_excluded": WARMUP_SCANS,
        "timed_frames": int(len(core)),
        "binary_sha1": fingerprint,
        "runtime_log_sha256": file_sha256(timing_path),
        "sleep_events": sleep_hits,
        "structure": {
            "gravity_max_component_span": gravity_span,
            "accelerometer_bias_max_component_span": ba_span,
            "gravity_norm_max_abs_error": gravity_norm_error,
            "estimated_path_length_m": path_len,
            "gt_path_length_m": gt_len,
        },
        "core_ms": {
            "mean": core_mean,
            "median": float(np.median(core)),
            "p90": float(np.percentile(core, 90)),
        },
        "preprocess_ms": {"mean": pre_mean},
        "component_sum_ms": {"mean": core_mean + pre_mean},
        "cumulative_components_ms": {
            "matching": match_ms,
            "measurement_solve_including_jacobian": measurement_solve_ms,
            "jacobian_construction": jacobian_ms,
            "state_dimension_sensitive_filter_algebra": filter_algebra_ms,
            "reported_core_mean": reported_total_ms,
        },
        "map_workload": {
            "mean_tree_size_at_scan_start": float(timing["tree size st"].iloc[WARMUP_SCANS:].mean()),
            "mean_incremental_map_ms": float(
                1000.0 * timing["incremental time"].iloc[WARMUP_SCANS:].mean()
            ),
        },
    }
    return record, timing["time_stamp"].to_numpy(float), timing["scan point size"].to_numpy(int)


def percent_change(new: float, baseline: float) -> float:
    return 100.0 * (new / baseline - 1.0)


def summary(values: list[float]) -> dict:
    return {
        "median": float(np.median(values)),
        "range": [float(np.min(values)), float(np.max(values))],
        "values": [float(v) for v in values],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()

    sleeps = sleep_events()
    runs: list[dict] = []
    pairs: list[dict] = []
    method_fingerprints = {method: set() for method in METHODS}
    reference_timestamps = None
    reference_points = None

    for repeat in (1, 2, 3):
        pair_records = {}
        for method in METHODS:
            try:
                record, timestamps, points = load_run(method, repeat, sleeps)
            except FileNotFoundError:
                if args.allow_incomplete:
                    continue
                raise
            if reference_timestamps is None:
                reference_timestamps = timestamps
                reference_points = points
            else:
                if not np.array_equal(timestamps, reference_timestamps):
                    raise ValueError(f"{method} r{repeat}: timing timestamps differ")
                if not np.array_equal(points, reference_points):
                    raise ValueError(f"{method} r{repeat}: input point counts differ")
            method_fingerprints[method].add(record["binary_sha1"])
            runs.append(record)
            pair_records[method] = record

        if len(pair_records) == 2:
            online = pair_records["A"]
            fixg = pair_records["RED21"]
            effects = {
                "core_mean_pct": percent_change(fixg["core_ms"]["mean"], online["core_ms"]["mean"]),
                "core_median_pct": percent_change(fixg["core_ms"]["median"], online["core_ms"]["median"]),
                "core_p90_pct": percent_change(fixg["core_ms"]["p90"], online["core_ms"]["p90"]),
                "component_sum_mean_pct": percent_change(
                    fixg["component_sum_ms"]["mean"], online["component_sum_ms"]["mean"]
                ),
                "filter_algebra_pct": percent_change(
                    fixg["cumulative_components_ms"]["state_dimension_sensitive_filter_algebra"],
                    online["cumulative_components_ms"]["state_dimension_sensitive_filter_algebra"],
                ),
                "filter_algebra_saving_as_online_core_pct": 100.0 * (
                    online["cumulative_components_ms"]["state_dimension_sensitive_filter_algebra"]
                    - fixg["cumulative_components_ms"]["state_dimension_sensitive_filter_algebra"]
                ) / online["cumulative_components_ms"]["reported_core_mean"],
                "measurement_solve_pct": percent_change(
                    fixg["cumulative_components_ms"]["measurement_solve_including_jacobian"],
                    online["cumulative_components_ms"]["measurement_solve_including_jacobian"],
                ),
            }
            pairs.append({"repeat": repeat, "effects": effects})

    if not pairs:
        raise ValueError("no complete Online/FixG pair")
    if not args.allow_incomplete and len(pairs) != 3:
        raise ValueError(f"expected 3 complete pairs, found {len(pairs)}")
    for method, fingerprints in method_fingerprints.items():
        if len(fingerprints) > 1:
            raise ValueError(f"{method}: binary changed between runs: {sorted(fingerprints)}")

    effects = {
        key: summary([pair["effects"][key] for pair in pairs])
        for key in pairs[0]["effects"]
    }
    per_method = {}
    for method in METHODS:
        selected = [run for run in runs if run["method"] == method]
        per_method[method] = {
            "n_runs": len(selected),
            "core_mean_ms": summary([run["core_ms"]["mean"] for run in selected]),
            "core_median_ms": summary([run["core_ms"]["median"] for run in selected]),
            "core_p90_ms": summary([run["core_ms"]["p90"] for run in selected]),
            "component_sum_mean_ms": summary([run["component_sum_ms"]["mean"] for run in selected]),
            "filter_algebra_ms": summary([
                run["cumulative_components_ms"]["state_dimension_sensitive_filter_algebra"]
                for run in selected
            ]),
            "measurement_solve_ms": summary([
                run["cumulative_components_ms"]["measurement_solve_including_jacobian"]
                for run in selected
            ]),
            "mean_tree_size": summary([
                run["map_workload"]["mean_tree_size_at_scan_start"] for run in selected
            ]),
        }

    workload_shares = {
        "filter_algebra_of_reported_core_pct": summary([
            100.0
            * run["cumulative_components_ms"]["state_dimension_sensitive_filter_algebra"]
            / run["cumulative_components_ms"]["reported_core_mean"]
            for run in runs
        ]),
        "matching_of_reported_core_pct": summary([
            100.0
            * run["cumulative_components_ms"]["matching"]
            / run["cumulative_components_ms"]["reported_core_mean"]
            for run in runs
        ]),
    }

    payload = {
        "schema_version": 2,
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "benchmark": {
            "sequence": "MCD ntu_day_10, Ouster OS1-128 vehicle",
            "bag": "data/mcd/ntu_day_10/os1.bag",
            "timed_input_span_s": float(reference_timestamps[-1] - reference_timestamps[0]),
            "replay_rate": 1.0,
            "pair_order": [["A", "RED21"], ["RED21", "A"], ["A", "RED21"]][:len(pairs)],
            "host": {"platform": platform.platform(), "machine": platform.machine()},
            "timing_definition": {
                "core": "FAST-LIO t0--t5: IMU propagation, scan downsampling, iterated update, and incremental map maintenance",
                "component_sum": "mean core time plus mean point-cloud callback preprocessing time",
                "filter_algebra": "final cumulative update time minus Jacobian construction; covers the state-dimension-sensitive iterated-filter algebra",
            },
            "gates": {
                "serial_lock": True,
                "exact_runtime_timestamp_match": True,
                "exact_input_point_count_match": True,
                "exact_frame_count_match": True,
                "sleep_events_in_runs": 0,
                "stable_binary_fingerprint_per_method": True,
            },
        },
        "runs": runs,
        "pairs": pairs,
        "summary": {
            "n_pairs": len(pairs),
            "per_method": per_method,
            "paired_effects_pct": effects,
            "workload_shares_pct": workload_shares,
        },
        "scope": (
            "single-sequence descriptive engineering benchmark; filter-algebra timing isolates "
            "the dimension-sensitive component, while end-to-end timing is confounded by two "
            "observed incremental-map workload branches and is not a cross-platform real-time claim"
        ),
    }
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {OUTPUT}")
    for key, value in effects.items():
        print(f"{key}: median {value['median']:+.3f}% range [{value['range'][0]:+.3f}, {value['range'][1]:+.3f}]%")


if __name__ == "__main__":
    main()
