#!/usr/bin/env python3
"""Generate the manuscript's true-dimension figures from audited results."""
import json
import hashlib
import re
import statistics
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Polygon, Wedge
import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
OUT = ROOT / "paper" / "figs"
OUT.mkdir(parents=True, exist_ok=True)

CORE = [
    ("ntu_day_01_os1", "ntu-d01"),
    ("ntu_day_02_os1", "ntu-d02"),
    ("ntu_day_10_os1", "ntu-d10"),
    ("ntu_night_04_os1", "ntu-n04"),
    ("ntu_night_13_os1", "ntu-n13"),
    ("kth_day_10_os1", "kth-d10"),
    ("kth_night_05_os1", "kth-n05"),
    ("tuhh_day_02_os1", "tuhh-d02"),
    ("tuhh_day_04_os1", "tuhh-d04"),
    ("tuhh_night_09_os1", "tuhh-n09"),
    ("IndoorOffice1", "tiers-office"),
    ("hall_05_run", "m2dgr-hall"),
]

# Restrained cool palette for final-size print. A slate navy carries the
# primary FixG comparison; an oxblood accent is reserved for dropout and harm.
# Every semantic distinction also has a line style, marker, sign, or direct
# label, so hue is never the only channel.
INK = "#20262C"
MUTED = "#68727C"
FAINT = "#B7C0C7"
GRID = "#D8DEE3"
PAPER = "#F3F5F6"
HERO = "#3E5C76"
ACCENT = "#873B46"
VIOLET = "#685A78"
NEUTRAL_FILL = "#ECEFF1"
HERO_FILL = "#E8EDF2"
ACCENT_FILL = "#F2E7EA"
VIOLET_FILL = "#EDEAF1"
QUIET_FILL = "#F8F9F9"
COLORS = {
    "A": "#36414A",
    "RED21": HERO,
    "RED20": MUTED,
    "RED18": ACCENT,
}
PALE = {
    "A": PAPER,
    "RED21": HERO_FILL,
    "RED20": NEUTRAL_FILL,
    "RED18": ACCENT_FILL,
}
MARKERS = {"RED21": "o", "RED20": "s", "RED18": "^"}
LABELS = {
    "A": "Online (23D)",
    "RED21": "FixG (21D)",
    "RED20": "FixBa (20D)",
    "RED18": "FixG+Ba (18D)",
}

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Arial", "DejaVu Sans", "Liberation Sans"],
    "font.size": 7.2,
    "axes.labelsize": 7.2,
    "axes.titlesize": 7.6,
    "xtick.labelsize": 6.6,
    "ytick.labelsize": 6.6,
    "legend.fontsize": 6.5,
    "axes.spines.right": False,
    "axes.spines.top": False,
    "axes.linewidth": 0.75,
    "axes.edgecolor": INK,
    "axes.labelweight": 700,
    "xtick.major.width": 0.7,
    "ytick.major.width": 0.7,
    "xtick.major.size": 2.5,
    "ytick.major.size": 2.5,
    "pdf.fonttype": 42,
    "svg.fonttype": "none",
})


def summary():
    return json.loads((ROOT / "report" / "summary.json").read_text())["sequences"]


def liosam_summary():
    data = strengthening_summary()
    block = data["liosam_new_sequences"]
    sequences = block["previous_sequences"] + block["new_sequences"]
    if len(sequences) != block["total_sequence_units"]:
        raise RuntimeError("LIO-SAM state-ablation sequence count is inconsistent")
    return {"sequences": sequences}


def direction_summary():
    return json.loads((ROOT / "report" / "liosam_direction.json").read_text())


def strengthening_summary():
    data = json.loads(
        (ROOT / "report" / "strengthening_20260831.json").read_text()
    )
    if data.get("status") != "completed_with_documented_failed_outcomes":
        raise RuntimeError("strengthening campaign is not in its final audited state")
    return data


def equivalence_sensitivity_summary():
    path = ROOT / "report" / "equivalence_sensitivity.json"
    if not path.exists():
        raise FileNotFoundError(
            "missing report/equivalence_sensitivity.json; run "
            "scripts/collect_equivalence_sensitivity.py"
        )
    data = json.loads(path.read_text())
    if data.get("status") != "complete_existing_results_only":
        raise RuntimeError("equivalence sensitivity analysis is not validated")
    return data


def mechanism_trace_summary():
    path = ROOT / "report" / "mechanism_trace.json"
    if not path.exists():
        raise FileNotFoundError(
            "missing report/mechanism_trace.json; run "
            "scripts/collect_mechanism_trace.py"
        )
    return json.loads(path.read_text())


def design_pointcloud_summary():
    manifest_path = ROOT / "report" / "design_pointcloud.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            "missing report/design_pointcloud.json; run "
            "scripts/collect_design_pointcloud.py"
        )
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema_version", 0) < 5:
        raise RuntimeError(
            "design point cloud predates the ROS1 RViz intensity audit; rerun "
            "scripts/collect_design_pointcloud.py"
        )
    if not manifest["source"].get(
            "intensity_multiset_matches_retained_raw", False):
        raise RuntimeError("design point-cloud intensity provenance is not verified")
    cloud_path = ROOT / manifest["artifact"]["path"]
    if not cloud_path.exists():
        raise FileNotFoundError(
            f"missing {cloud_path}; run scripts/collect_design_pointcloud.py"
        )
    digest = hashlib.sha256(cloud_path.read_bytes()).hexdigest()
    if digest != manifest["artifact"]["sha256"]:
        raise RuntimeError("design point-cloud hash does not match its manifest")
    with np.load(cloud_path) as archive:
        xyz = archive["xyz"]
        if "intensity" not in archive.files:
            raise RuntimeError(
                "design point cloud has no intensity; rerun "
                "scripts/collect_design_pointcloud.py"
            )
        intensity = archive["intensity"]
    if xyz.ndim != 2 or xyz.shape[1] != 3 or not np.isfinite(xyz).all():
        raise RuntimeError("design point cloud is not finite Nx3 data")
    if (intensity.ndim != 1 or len(intensity) != len(xyz)
            or not np.isfinite(intensity).all() or np.any(intensity < 0)):
        raise RuntimeError("design point-cloud intensity is not finite nonnegative N data")
    counts = manifest["counts"]
    interventions = manifest["interventions"]
    radius = np.linalg.norm(xyz[:, :2], axis=1)
    azimuth = np.abs(np.arctan2(xyz[:, 1], xyz[:, 0]))
    observed = {
        "finite_points": len(xyz),
        "range_retained": int((radius < interventions["range_limit_m"]).sum()),
        "fov_retained": int((azimuth < np.deg2rad(
            interventions["fov_half_angle_deg"])).sum()),
    }
    if observed != counts:
        raise RuntimeError(
            f"design point-cloud counts differ from manifest: {observed} != {counts}"
        )
    visual = manifest["visualization"]
    renderer = visual.get("renderer", {})
    expected_renderer = {
        "implementation": "ROS1 RViz IntensityPCTransformer",
        "display_name": "surround",
        "topic": "/cloud_registered",
        "color_transformer": "Intensity",
        "channel_name": "intensity",
        "autocompute_intensity_bounds": True,
        "use_rainbow": True,
        "invert_rainbow": False,
        "alpha": 1.0,
        "style": "Points",
        "size_pixels": 3,
        "background_rgb": [0, 0, 0],
    }
    mismatches = {
        key: (renderer.get(key), value)
        for key, value in expected_renderer.items()
        if renderer.get(key) != value
    }
    if mismatches:
        raise RuntimeError(
            f"design point-cloud renderer differs from FAST-LIO RViz: {mismatches}"
        )
    masks = {
        "nominal": np.ones(len(xyz), dtype=bool),
        "range": radius < interventions["range_limit_m"],
        "fov": azimuth < np.deg2rad(interventions["fov_half_angle_deg"]),
    }
    observed_bounds = {
        key: [float(np.min(intensity[mask])), float(np.max(intensity[mask]))]
        for key, mask in masks.items()
    }
    if observed_bounds != visual.get("intensity_bounds"):
        raise RuntimeError(
            "design point-cloud RViz intensity bounds differ from manifest"
        )
    return manifest, xyz, intensity


def rviz_rainbow_colors(values, minimum, maximum, *, invert=False):
    """Vectorized ROS1 RViz IntensityPCTransformer rainbow transfer.

    This follows rviz/noetic's point_cloud_transformers.cpp exactly: the
    intensity channel is linearly normalized with per-message min/max bounds,
    reversed before the five-segment HSV rainbow, then optionally inverted.
    """
    values = np.asarray(values, dtype=np.float64)
    diff = float(maximum) - float(minimum)
    if diff == 0:
        diff = 1e20
    value = 1.0 - (values - float(minimum)) / diff
    if invert:
        value = 1.0 - value
    value = np.clip(value, 0.0, 1.0)
    hue = value * 5.0 + 1.0
    segment = np.floor(hue).astype(np.int64)
    fraction = hue - segment
    fraction = np.where((segment & 1) == 0, 1.0 - fraction, fraction)
    complement = 1.0 - fraction
    colors = np.zeros((len(values), 3), dtype=np.float64)
    mask = segment <= 1
    colors[mask] = np.column_stack(
        (complement[mask], np.zeros(mask.sum()), np.ones(mask.sum())))
    mask = segment == 2
    colors[mask] = np.column_stack(
        (np.zeros(mask.sum()), complement[mask], np.ones(mask.sum())))
    mask = segment == 3
    colors[mask] = np.column_stack(
        (np.zeros(mask.sum()), np.ones(mask.sum()), complement[mask]))
    mask = segment == 4
    colors[mask] = np.column_stack(
        (complement[mask], np.ones(mask.sum()), np.zeros(mask.sum())))
    mask = segment >= 5
    colors[mask] = np.column_stack(
        (np.ones(mask.sum()), complement[mask], np.zeros(mask.sum())))
    return colors


def save(fig, name):
    # SVG is the editable primary artifact; PDF is embedded in LaTeX and PNG is QA-only.
    for ext in ("svg", "pdf", "png"):
        kwargs = {"dpi": 300} if ext == "png" else {}
        fig.savefig(OUT / f"{name}.{ext}", bbox_inches="tight",
                    pad_inches=0.02, facecolor="white", **kwargs)
    plt.close(fig)
    print(f"{name}.pdf/.svg/.png")


def panel_title(ax, letter, title):
    ax.text(-0.02, 1.035, letter, transform=ax.transAxes, ha="right", va="bottom",
            fontsize=8.0, fontweight=700, color=INK)
    ax.text(0.02, 1.035, title, transform=ax.transAxes, ha="left", va="bottom",
            fontsize=7.6, fontweight=700, color=INK)


def horizontal_guides(ax, ticks):
    for tick in ticks:
        ax.axhline(tick, color=GRID, lw=0.50, zorder=0)


def grav_angle(path):
    d = pd.read_csv(path).dropna()
    t = d["t"].to_numpy() - d["t"].iloc[0]
    g = d[["gx", "gy", "gz"]].to_numpy()
    unit = g / np.linalg.norm(g, axis=1, keepdims=True)
    ref = unit[0]
    angle = np.degrees(np.arccos(np.clip(unit @ ref, -1.0, 1.0)))
    return t, angle


def fig_design():
    """True-dimensional factorial design and controlled observation regimes."""
    fig, axes = plt.subplots(
        2, 1, figsize=(3.35, 4.18),
        gridspec_kw={"height_ratios": [1.12, 0.88]},
    )

    ax = axes[0]
    ax.set_xlim(-0.42, 2.05)
    ax.set_ylim(-0.20, 2.08)
    ax.axis("off")
    panel_title(ax, "a", "True-dimensional factorial ablation")
    ax.text(0.46, 1.84, "gravity online", ha="center", va="center",
            fontsize=6.5, color=MUTED)
    ax.text(1.49, 1.84, "gravity fixed", ha="center", va="center",
            fontsize=6.5, color=MUTED)
    ax.text(-0.18, 1.31, r"$\mathbf{b}_a$ online", ha="center", va="center",
            fontsize=6.5, color=MUTED, rotation=90)
    ax.text(-0.18, 0.40, r"$\mathbf{b}_a$ fixed", ha="center", va="center",
            fontsize=6.5, color=MUTED, rotation=90)
    cards = (
        (0.08, 1.00, "Online", "23D full / 17D active", "A"),
        (1.11, 1.00, "FixG", "21D full / 15D active", "RED21"),
        (0.08, 0.10, "FixBa", "20D full / 14D active", "RED20"),
        (1.11, 0.10, "FixG+Ba", "18D full / 12D active", "RED18"),
    )
    for x, y, name, dim, method in cards:
        card = FancyBboxPatch(
            (x, y), 0.76, 0.58,
            boxstyle="round,pad=0.025,rounding_size=0.035",
            facecolor=PALE[method], edgecolor=COLORS[method], linewidth=1.0,
        )
        ax.add_patch(card)
        ax.text(x + 0.38, y + 0.36, name, ha="center", va="center",
                fontsize=7.3, fontweight="bold", color=COLORS[method])
        ax.text(x + 0.38, y + 0.17, dim, ha="center", va="center",
                fontsize=5.4, color=MUTED)
    ax.annotate("", xy=(1.08, 1.72), xytext=(0.87, 1.72),
                arrowprops={"arrowstyle": "-|>", "lw": 0.75,
                            "color": COLORS["RED21"]})
    ax.text(0.975, 1.64, "$-2$D", ha="center", va="top", fontsize=5.8,
            color=COLORS["RED21"])
    ax.annotate("", xy=(1.96, 0.71), xytext=(1.96, 0.98),
                arrowprops={"arrowstyle": "-|>", "lw": 0.75,
                            "color": COLORS["RED20"]})
    ax.text(2.00, 0.845, "$-3$D", ha="left", va="center", fontsize=5.8,
            color=COLORS["RED20"], rotation=90)

    ax = axes[1]
    ax.set_xlim(-3.8, 21.8)
    ax.set_ylim(-0.45, 3.30)
    ax.axis("off")
    panel_title(ax, "b", "Controlled observation regimes")
    rows = (
        (2.35, "nominal", 0, "original scan stream", "A"),
        (1.35, "degraded", 0, "range cap or narrow FoV", "RED20"),
        (0.35, "absent", 3, "1--5 s complete dropout", "RED18"),
    )
    for y, label, gap, outcome, method in rows:
        ax.text(-0.25, y, label, ha="right", va="center", fontsize=6.6,
                fontweight="bold", color=INK)
        ax.hlines(y, 0, 14, color=GRID, lw=1.0, zorder=1)
        gap_start, gap_end = 6.0, 6.0 + 0.7 * gap
        if gap:
            ax.fill_between((gap_start, gap_end), y - 0.26, y + 0.26,
                            color=PALE[method], zorder=0)
            ax.vlines((gap_start, gap_end), y - 0.24, y + 0.24,
                      color=COLORS[method], lw=0.7, ls=(0, (2, 2)), zorder=2)
        update_times = np.arange(0, 14.01, 0.56)
        if gap:
            update_times = update_times[(update_times < gap_start) | (update_times > gap_end)]
        ax.vlines(update_times, y - 0.12, y + 0.12, color=COLORS["RED21"],
                  lw=0.8, zorder=3)
        ax.annotate("", xy=(14.85, y), xytext=(14.15, y),
                    arrowprops={"arrowstyle": "-|>", "lw": 0.65,
                                "color": MUTED})
        ax.text(15.15, y, outcome, ha="left", va="center", fontsize=6.1,
                color=COLORS[method])
    ax.annotate("", xy=(14, -0.18), xytext=(0, -0.18),
                arrowprops={"arrowstyle": "|-|", "lw": 0.65, "color": MUTED})
    ax.text(7, -0.31, "one 20 s cycle", ha="center", va="top",
            fontsize=6.0, color=MUTED)
    ax.vlines(0.4, 3.03, 3.25, color=COLORS["RED21"], lw=0.9)
    ax.text(0.85, 3.14, "LiDAR update", va="center", fontsize=5.9, color=MUTED)
    key = FancyBboxPatch((7.0, 3.03), 1.1, 0.22,
                         boxstyle="round,pad=0.01,rounding_size=0.02",
                         facecolor=PALE["RED20"], edgecolor="none")
    ax.add_patch(key)
    ax.text(8.5, 3.14, "no update", va="center", fontsize=5.9, color=MUTED)

    fig.subplots_adjust(left=0.075, right=0.99, bottom=0.055, top=0.955,
                        hspace=0.34)
    save(fig, "fig_design")


def fig_teaser():
    """The whole paper in one figure: motion, equivalence, and boundary."""
    S = summary()
    fig, axes = plt.subplots(
        1, 3, figsize=(7.15, 2.62),
        gridspec_kw={"width_ratios": [0.78, 1.22, 0.98]},
    )

    ax = axes[0]
    traces = [
        ("ntu_night_04_os1", "ntu-n04"),
        ("ntu_day_01_os1", "ntu-d01"),
        ("ntu_day_10_os1", "ntu-d10"),
    ]
    trace_colors = (INK, MUTED, FAINT)
    for (seq, label), color in zip(traces, trace_colors):
        t, angle = grav_angle(RESULTS / seq / "A" / "state_log.csv")
        ax.plot(t / 60.0, angle, lw=1.05, color=color)
        ax.annotate(label, (t[-1] / 60.0, angle[-1]), xytext=(-2, 2),
                    textcoords="offset points", ha="right", va="bottom",
                    fontsize=5.9, color=color)
    t, angle = grav_angle(RESULTS / "ntu_night_04_os1" / "RED21" / "state_log.csv")
    ax.plot(t / 60.0, angle, lw=1.35, color=COLORS["RED21"])
    ax.annotate("FixG: fixed", (t[-1] / 60.0, 0), xytext=(-2, 4),
                textcoords="offset points", ha="right", fontsize=6,
                color=COLORS["RED21"])
    ax.set_xlabel("time [min]")
    ax.set_ylabel("gravity-direction change [$^\\circ$]")
    panel_title(ax, "a", "Online gravity moves")
    ax.set_ylim(-0.2, 4.25)
    ax.set_yticks((0, 1, 2, 3, 4))
    horizontal_guides(ax, (0, 2, 4))

    ax = axes[1]
    y = np.arange(len(CORE))[::-1]
    z_eff, a_eff = [], []
    for seq, _ in CORE:
        runs = S[seq]["runs"]
        z_eff.append(100 * (runs["RED21"]["rmse_z_m"] / runs["A"]["rmse_z_m"] - 1))
        a_eff.append(100 * (runs["RED21"]["ate_rmse_m"] / runs["A"]["ate_rmse_m"] - 1))
    ax.axvspan(-5, 5, color=PALE["RED21"], zorder=0)
    ax.axvline(0, color=INK, lw=0.75, zorder=1)
    for yi in y:
        ax.hlines(yi, -8, 8, color=GRID, lw=0.45, zorder=0)
    ax.scatter(z_eff, y + 0.13, s=18, marker="o", facecolor=COLORS["RED21"],
               edgecolor="white", linewidth=0.35, zorder=3, label="RMSE$_z$")
    ax.scatter(a_eff, y - 0.13, s=21, marker="D", facecolor="white",
               edgecolor=INK, linewidth=0.9, zorder=3, label="ATE")
    ax.set_yticks(y, [label for _, label in CORE])
    ax.set_xlabel("FixG relative to Online [%]")
    ax.set_xlim(-8.0, 8.0)
    ax.set_xticks((-5, 0, 5))
    ax.set_ylim(-0.65, len(CORE) - 0.35)
    panel_title(ax, "b", "No pose benefit with continuous correction")
    ax.text(-4.75, len(CORE) - 0.72, "$\\pm$5% equivalence region", ha="left",
            va="top", fontsize=5.9, color=COLORS["RED21"])
    ax.legend(frameon=False, ncol=2, loc="lower right", handlelength=1.0,
              columnspacing=0.8, borderaxespad=0.2)

    ax = axes[2]
    z = boundary_series(S, "RED21", "rmse_z_m")
    a = boundary_series(S, "RED21", "ate_rmse_m")
    z_effect = 100 * (z[:, 1] - 1)
    a_effect = 100 * (a[:, 1] - 1)
    ax.axhline(0, color=INK, lw=0.75, ls=(0, (3, 2)), zorder=1)
    ax.axvspan(2, 3, color=PAPER, zorder=0)
    ax.plot(z[:, 0], z_effect, color=COLORS["RED21"], marker="o",
            ms=4.0, lw=1.25, markerfacecolor=COLORS["RED21"],
            markeredgecolor="white", markeredgewidth=0.45,
            label="RMSE$_z$")
    ax.plot(a[:, 0], a_effect, color=INK, marker="D",
            ms=3.8, lw=1.15, markerfacecolor="white",
            markeredgewidth=0.9, label="ATE")
    horizontal_guides(ax, (0, 50, 100))
    ax.set_xlabel("LiDAR dropout per 20 s [s]")
    ax.set_ylabel("FixG relative to Online [%]")
    ax.set_xticks((0, 1, 2, 3, 5))
    ax.set_ylim(-24, 138)
    ax.set_yticks((0, 50, 100))
    panel_title(ax, "c", "A correction gap can activate the state")
    ax.text(2.5, 131, "transition", ha="center", va="top",
            fontsize=5.7, color=MUTED)
    ax.annotate(f"{z_effect[3]:+.0f}% / {a_effect[3]:+.0f}%",
                xy=(3, max(z_effect[3], a_effect[3])), xytext=(3.18, 126),
                ha="left", va="center", fontsize=5.8, color=INK,
                arrowprops={"arrowstyle": "-", "lw": 0.55,
                            "color": MUTED})
    ax.legend(frameon=False, loc="lower right", handlelength=1.2,
              borderaxespad=0.2)

    fig.subplots_adjust(left=0.067, right=0.995, bottom=0.18, top=0.88, wspace=0.39)
    save(fig, "fig_teaser")


def repeat_values(runs, method, metric, repeats):
    pattern = re.compile(rf"^{re.escape(method)}_r\d+$")
    values = []
    for name, rec in runs.items():
        if name != method and not (repeats and pattern.match(name)):
            continue
        if rec.get("usable", True) is not False and rec.get(metric) is not None:
            values.append(float(rec[metric]))
    return np.asarray(values)


def boundary_series(S, method, metric):
    points = []
    for seconds in (0, 1, 2, 3, 5):
        seq = "ntu_day_10_os1" if seconds == 0 else f"ntu_day_10_drop{seconds}x20"
        runs = S[seq]["runs"]
        repeats = seconds in (2, 3)
        a = repeat_values(runs, "A", metric, repeats)
        m = repeat_values(runs, method, metric, repeats)
        ratios = m / np.median(a)
        points.append((seconds, float(np.median(ratios)),
                       float(np.min(ratios)), float(np.max(ratios))))
    return np.asarray(points)


def fig_factorial():
    """Population equivalence, cross-estimator validation, and factorial effects."""
    S = summary()
    LS = liosam_summary()
    fig = plt.figure(figsize=(7.15, 5.02))
    gs = fig.add_gridspec(2, 6, height_ratios=(0.64, 2.36),
                          hspace=0.50, wspace=0.24)
    ax_ci = fig.add_subplot(gs[0, :4])
    ax_lio = fig.add_subplot(gs[0, 4:])
    axes = (fig.add_subplot(gs[1, :2]), fig.add_subplot(gs[1, 2:4]),
            fig.add_subplot(gs[1, 4:]))
    y = np.arange(len(CORE))[::-1]

    def population_ci(metric):
        ratios = np.asarray([
            S[seq]["runs"]["RED21"][metric] / S[seq]["runs"]["A"][metric]
            for seq, _ in CORE
        ])
        lr = np.log(ratios)
        half = stats.t.ppf(0.95, len(lr) - 1) * stats.sem(lr)
        values = 100 * (np.exp((lr.mean() - half, lr.mean(), lr.mean() + half)) - 1)
        return values

    ax_ci.axvspan(-5, 5, color=PALE["RED21"], zorder=0)
    ax_ci.axvline(0, color=INK, lw=0.75, zorder=1)
    for yi, metric, label, marker in (
            (1, "rmse_z_m", "RMSE$_z$", "o"),
            (0, "ate_rmse_m", "ATE", "D")):
        lo, mean, hi = population_ci(metric)
        ax_ci.errorbar(mean, yi, xerr=[[mean - lo], [hi - mean]],
                       color=COLORS["RED21"], marker=marker, ms=4.5,
                       lw=1.25, capsize=2.2, markerfacecolor="white",
                       markeredgewidth=1.0, zorder=3)
        ax_ci.text(5.25, yi, f"{mean:+.2f}%  [{lo:+.2f}, {hi:+.2f}]",
                   ha="left", va="center", fontsize=6.3,
                   color=COLORS["RED21"])
    ax_ci.set_yticks((1, 0), ("RMSE$_z$", "ATE"))
    ax_ci.set_xlim(-6.3, 8.8)
    ax_ci.set_xticks((-5, 0, 5))
    ax_ci.set_ylim(-0.55, 1.55)
    ax_ci.set_xlabel("population mean paired effect [%, 90% CI]")
    panel_title(ax_ci, "a", "FixG is equivalent under continuous correction")
    ax_ci.text(-4.8, 1.42, r"pre-specified $\pm$5% margin", ha="left",
               va="top", fontsize=5.8, color=MUTED)

    lio_sequences = LS["sequences"]
    lio_y = np.arange(len(lio_sequences))[::-1]
    lio_labels = []
    for yi, entry in zip(lio_y, lio_sequences):
        sequence = entry["sequence"].lower()
        lio_labels.append("Hall05" if "hall" in sequence else "TUHH")
        runs = entry["runs"]
        z_effect = 100 * (runs["GE-BA"]["rmse_z_m"] /
                          runs["FG-BA"]["rmse_z_m"] - 1)
        ate_effect = 100 * (runs["GE-BA"]["ate_rmse_m"] /
                            runs["FG-BA"]["ate_rmse_m"] - 1)
        ax_lio.hlines(yi, min(z_effect, ate_effect), max(z_effect, ate_effect),
                      color=FAINT, lw=1.0, zorder=1)
        ax_lio.scatter(z_effect, yi + 0.08, s=20, marker="o",
                       facecolor=HERO, edgecolor="white", linewidth=0.35,
                       zorder=3, label="RMSE$_z$" if yi == lio_y[0] else None)
        ax_lio.scatter(ate_effect, yi - 0.08, s=22, marker="D",
                       facecolor="white", edgecolor=INK, linewidth=0.85,
                       zorder=3, label="ATE" if yi == lio_y[0] else None)
    ax_lio.axvline(0, color=INK, lw=0.75, zorder=0)
    ax_lio.set_xlim(-0.70, 0.70)
    ax_lio.set_xticks((-0.5, 0, 0.5))
    ax_lio.set_yticks(lio_y, lio_labels)
    ax_lio.set_ylim(-0.55, 1.55)
    ax_lio.set_xlabel("GE-BA relative to FG-BA [%]", labelpad=1.5)
    panel_title(ax_lio, "b", "Factor graph: no online-$g$ gain")
    ax_lio.legend(frameon=False, ncol=1, loc="upper right",
                  borderaxespad=0.15, handlelength=0.8,
                  labelspacing=0.25, fontsize=5.5)

    ax = axes[0]
    z_abs = [S[seq]["runs"]["A"]["rmse_z_m"] for seq, _ in CORE]
    ate_abs = [S[seq]["runs"]["A"]["ate_rmse_m"] for seq, _ in CORE]
    for yi, zv, av in zip(y, z_abs, ate_abs):
        ax.hlines(yi, min(zv, av), max(zv, av), color=GRID, lw=0.7,
                  zorder=1)
    ax.scatter(z_abs, y + 0.12, s=17, color=INK, edgecolor="white",
               linewidth=0.35, zorder=3, label="RMSE$_z$")
    ax.scatter(ate_abs, y - 0.12, s=20, marker="D", facecolor="white",
               edgecolor=INK, linewidth=0.85, zorder=3, label="ATE")
    ax.set_xscale("log")
    ax.set_xlim(0.01, 20)
    ax.set_xticks((0.01, 0.1, 1, 10), ("0.01", "0.1", "1", "10"))
    ax.set_yticks(y, [label for _, label in CORE])
    ax.set_xlabel("Online absolute error [m]\n(log scale)")
    ax.set_ylim(-0.65, len(CORE) - 0.35)
    panel_title(ax, "c", "Errors span orders of magnitude")
    ax.legend(frameon=False, loc="lower right", handlelength=0.9,
              borderaxespad=0.2)

    offsets = {"RED21": 0.20, "RED20": 0.0, "RED18": -0.20}
    limits = ((-12, 52), (-10, 18))
    ticks = ((0, 20, 40), (-5, 0, 5, 10, 15))
    for panel, (ax, metric, title, xlim, xticks) in enumerate(zip(
            axes[1:], ("rmse_z_m", "ate_rmse_m"),
            ("Bias removal drives vertical outliers",
             "Full-pose effects stay heterogeneous"),
            limits, ticks)):
        ax.axvspan(-5, 5, color=PAPER, zorder=0)
        ax.axvline(0, color=INK, lw=0.75, zorder=1)
        for yi in y:
            ax.hlines(yi, xlim[0], xlim[1], color=GRID, lw=0.45,
                      zorder=0)
        for method in ("RED21", "RED20", "RED18"):
            effects = []
            for seq, _ in CORE:
                runs = S[seq]["runs"]
                effects.append(100 * (runs[method][metric] /
                                      runs["A"][metric] - 1))
            ax.scatter(effects, y + offsets[method], s=19,
                       marker=MARKERS[method], facecolor="white",
                       edgecolor=COLORS[method], linewidth=0.95, zorder=3,
                       label=LABELS[method].split(" (")[0])
        ax.set_xlim(*xlim)
        ax.set_xticks(xticks)
        ax.set_yticks(y)
        ax.tick_params(axis="y", labelleft=False, length=0)
        ax.set_ylim(-0.65, len(CORE) - 0.35)
        ax.set_xlabel("paired change relative to Online [%]")
        panel_title(ax, "de"[panel], title)
    axes[1].text(-4.5, len(CORE) - 0.74, r"$\pm$5% region", ha="left",
                 va="top", fontsize=5.7, color=MUTED)
    handles, labels = axes[2].get_legend_handles_labels()
    axes[2].legend(handles, labels, frameon=False, ncol=1, loc="lower right",
                   borderaxespad=0.25, labelspacing=0.3, handlelength=0.9)
    fig.subplots_adjust(left=0.105, right=0.995, bottom=0.12, top=0.94)
    save(fig, "fig_factorial")


def fig_stress():
    """Mechanism stress tests: IMU trust, weak geometry, and missing updates."""
    S = summary()
    fig = plt.figure(figsize=(7.15, 4.15))
    gs = fig.add_gridspec(2, 6, height_ratios=(0.88, 1.0), hspace=0.68,
                          wspace=0.85)
    imu_axes = (fig.add_subplot(gs[0, :3]), fig.add_subplot(gs[0, 3:]))
    scales = np.asarray((0.01, 0.1, 1.0, 10.0))
    run_labels = ("0p01", "0p1", "1", "10")
    sequences = (
        ("ntu_day_10_os1", "day-10", COLORS["RED21"], "o"),
        ("ntu_night_04_os1", "night-04", COLORS["RED20"], "s"),
    )
    for panel, (ax, metric, title) in enumerate(zip(
            imu_axes, ("rmse_z_m", "ate_rmse_m"),
            ("IMU trust: vertical error", "IMU trust: full-pose error"))):
        ax.axhspan(-5, 5, color=PAPER, zorder=0)
        ax.axhline(0, color=INK, lw=0.75, zorder=1)
        for seq, label, color, marker in sequences:
            runs = S[seq]["runs"]
            effects = []
            for run_label in run_labels:
                online = runs[f"A_tdim_imuw{run_label}"][metric]
                fixg = runs[f"RED21_tdim_imuw{run_label}"][metric]
                effects.append(100 * (fixg / online - 1))
            ax.plot(scales, effects, color=color, marker=marker, ms=4.0,
                    lw=1.2, markerfacecolor="white", markeredgewidth=0.9)
            ax.annotate(label, (scales[-1], effects[-1]), xytext=(4, 0),
                        textcoords="offset points", ha="left", va="center",
                        fontsize=5.8, color=color)
        ax.set_xscale("log")
        ax.set_xticks(scales, ("0.01", "0.1", "1", "10"))
        ax.set_xlabel("IMU process-noise scale")
        ax.set_ylabel("FixG relative to Online [%]")
        ax.set_xlim(0.007, 16.0)
        horizontal_guides(ax, (-10, -5, 5, 10))
        panel_title(ax, "ab"[panel], title)
    imu_axes[0].set_ylim(-12.5, 11.0)
    imu_axes[1].set_ylim(-3.0, 11.0)
    imu_axes[0].text(0.008, 4.4, r"$\pm$5% region", fontsize=5.7,
                     color=MUTED, ha="left", va="top")

    ax_cont = fig.add_subplot(gs[1, :2])
    continuous = (
        ("ntu_day_10_os1", "nominal"),
        ("ntu_day_10_range20", "20 m range"),
        ("ntu_day_10_fov60", r"$\pm60^\circ$ FoV"),
    )
    cy = np.arange(len(continuous))[::-1]
    z_effect, ate_effect = [], []
    for seq, _ in continuous:
        runs = S[seq]["runs"]
        z_effect.append(100 * (runs["RED21"]["rmse_z_m"] /
                               runs["A"]["rmse_z_m"] - 1))
        ate_effect.append(100 * (runs["RED21"]["ate_rmse_m"] /
                                 runs["A"]["ate_rmse_m"] - 1))
    ax_cont.axvspan(-5, 5, color=PAPER, zorder=0)
    ax_cont.axvline(0, color=INK, lw=0.75, zorder=1)
    ax_cont.scatter(z_effect, cy + 0.11, s=19, marker="o",
                    facecolor=COLORS["RED21"], edgecolor="white",
                    linewidth=0.35, zorder=3, label="RMSE$_z$")
    ax_cont.scatter(ate_effect, cy - 0.11, s=21, marker="D",
                    facecolor="white", edgecolor=COLORS["RED21"],
                    linewidth=0.9, zorder=3, label="ATE")
    ax_cont.set_yticks(cy, [label for _, label in continuous])
    ax_cont.set_xlim(-8, 8)
    ax_cont.set_xticks((-5, 0, 5))
    ax_cont.set_xlabel("FixG relative to Online [%]")
    ax_cont.set_ylim(-0.55, 2.55)
    panel_title(ax_cont, "c", "Weaker geometry, same update rhythm")
    ax_cont.legend(frameon=False, loc="lower left", handlelength=0.9,
                   borderaxespad=0.15)

    drop_axes = (fig.add_subplot(gs[1, 2:4]), fig.add_subplot(gs[1, 4:]))
    for panel, (ax, metric, title, ylim, yticks) in enumerate(zip(
            drop_axes, ("rmse_z_m", "ate_rmse_m"),
            ("Dropout: vertical error", "Dropout: full-pose error"),
            ((-32, 248), (-32, 158)), ((0, 100, 200), (0, 50, 100, 150)))):
        ax.axhline(0, color=COLORS["A"], lw=0.75, ls=(0, (3, 2)), zorder=1)
        ax.axvspan(2, 3, color=PAPER, zorder=0)
        horizontal_guides(ax, yticks)
        for method in ("RED21", "RED20", "RED18"):
            p = boundary_series(S, method, metric)
            effect = 100 * (p[:, 1] - 1)
            lower = 100 * (p[:, 1] - p[:, 2])
            upper = 100 * (p[:, 3] - p[:, 1])
            ax.errorbar(p[:, 0], effect, yerr=np.vstack((lower, upper)),
                        color=COLORS[method], marker=MARKERS[method], ms=3.8,
                        lw=1.05, capsize=1.6, markerfacecolor="white",
                        markeredgewidth=0.9, label=LABELS[method].split(" (")[0])
        ax.set_xlabel("LiDAR dropout per 20 s [s]")
        ax.set_ylabel("change relative to Online [%]")
        ax.set_xticks((0, 1, 2, 3, 5))
        ax.set_ylim(*ylim)
        ax.set_yticks(yticks)
        panel_title(ax, "de"[panel], title)
    handles, labels = drop_axes[1].get_legend_handles_labels()
    fig.legend(handles, labels, frameon=False, ncol=3, loc="lower center",
               bbox_to_anchor=(0.70, 0.005), columnspacing=0.9,
               handlelength=1.1)
    fig.subplots_adjust(left=0.077, right=0.995, bottom=0.13, top=0.93)
    save(fig, "fig_stress")


def fig_boundary():
    """Continuous-degradation control and trajectory-dependent FixG dropout."""
    S = summary()
    fig = plt.figure(figsize=(7.15, 4.72))
    gs = fig.add_gridspec(2, 2, height_ratios=(0.62, 1.38),
                          hspace=0.62, wspace=0.30)
    axes = (fig.add_subplot(gs[0, :]), fig.add_subplot(gs[1, 0]),
            fig.add_subplot(gs[1, 1]))

    ax = axes[0]
    continuous = (
        ("ntu_day_10_os1", "nominal"),
        ("ntu_day_10_range20", "20 m range"),
        ("ntu_day_10_fov60", r"$\pm60^\circ$ FoV"),
    )
    y = np.arange(len(continuous))[::-1]
    z_effect, ate_effect = [], []
    for seq, _ in continuous:
        runs = S[seq]["runs"]
        z_effect.append(100 * (runs["RED21"]["rmse_z_m"] /
                               runs["A"]["rmse_z_m"] - 1))
        ate_effect.append(100 * (runs["RED21"]["ate_rmse_m"] /
                                 runs["A"]["ate_rmse_m"] - 1))
    ax.axvspan(-5, 5, color=PALE["RED21"], zorder=0)
    ax.axvline(0, color=INK, lw=0.75, zorder=1)
    for yi, z_value, ate_value in zip(y, z_effect, ate_effect):
        # A signed lollipop is more legible here than another response curve:
        # the stem shows direction and magnitude from the Online reference.
        ax.hlines(yi + 0.11, min(0, z_value), max(0, z_value),
                  color=COLORS["RED21"], lw=1.15, zorder=2)
        ax.hlines(yi - 0.11, min(0, ate_value), max(0, ate_value),
                  color=INK, lw=0.9, zorder=2)
    ax.scatter(z_effect, y + 0.11, s=20, marker="o",
               facecolor=COLORS["RED21"], edgecolor="white", linewidth=0.35,
               zorder=3, label="RMSE$_z$")
    ax.scatter(ate_effect, y - 0.11, s=22, marker="D", facecolor="white",
               edgecolor=INK, linewidth=0.9, zorder=3, label="ATE")
    ax.set_yticks(y, [label for _, label in continuous])
    ax.set_xlim(-8, 8)
    ax.set_xticks((-5, 0, 5))
    ax.set_ylim(-0.55, 2.55)
    ax.set_xlabel("FixG relative to Online [%]")
    panel_title(ax, "a", "Weak geometry preserves the small effect")
    ax.legend(frameon=False, ncol=2, loc="lower left", handlelength=0.9,
              borderaxespad=0.15)

    dropout_specs = (
        (axes[1], "ntu_day_10", "Vehicle cost jumps at 3 s", (0, 1, 2, 3, 5),
         (-28, 138), (0, 50, 100)),
        (axes[2], "tuhh_day_04", "Handheld cost grows later", (0, 2, 3, 5),
         (-8, 40), (0, 10, 20, 30, 40)),
    )
    metric_specs = (
        ("rmse_z_m", "RMSE$_z$", "o", COLORS["RED21"], "-"),
        ("ate_rmse_m", "ATE", "D", INK, "--"),
    )
    for panel, (ax, prefix, title, seconds_values, ylim, ticks) in enumerate(
            dropout_specs):
        ax.axhline(0.0, color=COLORS["A"], lw=0.8, ls=(0, (3, 2)), zorder=1)
        horizontal_guides(ax, ticks)
        if prefix == "ntu_day_10":
            ax.axvspan(2, 3, color=PAPER, zorder=0)
        for metric, label, marker, color, linestyle in metric_specs:
            points = []
            for seconds in seconds_values:
                seq = f"{prefix}_os1" if seconds == 0 else f"{prefix}_drop{seconds}x20"
                runs = S[seq]["runs"]
                repeats = prefix == "ntu_day_10" and seconds in (2, 3)
                a = repeat_values(runs, "A", metric, repeats)
                g = repeat_values(runs, "RED21", metric, repeats)
                ratios = g / np.median(a)
                points.append((seconds, float(np.median(ratios)),
                               float(np.min(ratios)), float(np.max(ratios))))
            p = np.asarray(points)
            effect = 100 * (p[:, 1] - 1)
            lower = 100 * (p[:, 1] - p[:, 2])
            upper = 100 * (p[:, 3] - p[:, 1])
            ax.errorbar(p[:, 0], effect, yerr=np.vstack((lower, upper)),
                        color=color, marker=marker, ms=4.2, lw=1.2,
                        ls=linestyle, capsize=1.8, markerfacecolor="white",
                        markeredgewidth=0.95, label=label)
        panel_title(ax, "bc"[panel], title)
        ax.set_xlabel("LiDAR dropout per 20 s [s]")
        ax.set_ylabel("FixG relative to Online [%]")
        ax.set_xticks(seconds_values)
        ax.set_ylim(*ylim)
        ax.set_yticks(ticks)
    axes[1].text(2.5, 131, "vehicle bracket", ha="center", va="top",
                 fontsize=5.8, color=MUTED)
    handles, labels = axes[2].get_legend_handles_labels()
    fig.legend(handles, labels, frameon=False, ncol=2, loc="lower center",
               bbox_to_anchor=(0.5, 0.005), columnspacing=1.2,
               handlelength=1.35)
    fig.subplots_adjust(left=0.075, right=0.995, bottom=0.15, top=0.94)
    save(fig, "fig_boundary")


def fig_imuweight():
    """True-manifold IMU-weight and initialization-error stress tests."""
    S = summary()
    scales = np.asarray((0.01, 0.1, 1.0, 10.0))
    run_labels = ("0p01", "0p1", "1", "10")
    sequences = (
        ("ntu_day_10_os1", "ntu-day-10", COLORS["RED21"], "o"),
        ("ntu_night_04_os1", "ntu-night-04", COLORS["RED20"], "s"),
    )
    fig, axes = plt.subplots(3, 1, figsize=(3.35, 5.36))
    for panel, (ax, metric, title) in enumerate(zip(
            axes,
            ("rmse_z_m", "ate_rmse_m"),
            ("No vertical IMU-weight dose response",
             "Full-pose response stays trajectory-specific"))):
        ax.axhspan(-5, 5, color=PAPER, zorder=0)
        ax.axhline(0, color=INK, lw=0.75, zorder=1)
        for seq, label, color, marker in sequences:
            runs = S[seq]["runs"]
            effects = []
            for run_label in run_labels:
                online = runs[f"A_tdim_imuw{run_label}"][metric]
                red21 = runs[f"RED21_tdim_imuw{run_label}"][metric]
                effects.append(100 * (red21 / online - 1))
            ax.plot(scales, effects, color=color, marker=marker, ms=4.3,
                    lw=1.25, markerfacecolor="white", markeredgewidth=0.95,
                    label=label)
            ax.annotate(label.replace("ntu-", ""), (scales[-1], effects[-1]),
                        xytext=(5, 0), textcoords="offset points", ha="left",
                        va="center", fontsize=5.9, color=color)
        ax.set_xscale("log")
        ax.set_xticks(scales, ("0.01", "0.1", "1", "10"))
        ax.set_xlabel("IMU process-noise scale")
        ax.set_ylabel("FixG relative to Online [%]")
        panel_title(ax, "ab"[panel], title)
        horizontal_guides(ax, (-10, -5, 5, 10))
        ax.set_xlim(0.007, 16.0)
    axes[0].set_ylim(-12.5, 11.0)
    axes[1].set_ylim(-3.0, 11.0)
    axes[0].text(0.008, 4.4, "$\\pm$5% region", fontsize=5.7,
                 color=MUTED, ha="left", va="top")

    ax = axes[2]
    ax.axvspan(-5, 5, color=PAPER, zorder=0)
    ax.axvline(0, color=INK, lw=0.75, zorder=1)
    init_labels = ("0p5", "1", "2")
    init_sequences = (
        ("ntu_day_10_os1", "vehicle"),
        ("tuhh_day_04_os1", "handheld"),
    )
    rows = []
    for seq, trajectory in init_sequences:
        runs = S[seq]["runs"]
        for angle, level in zip((0.5, 1.0, 2.0), init_labels):
            effects = []
            for metric in ("rmse_z_m", "ate_rmse_m"):
                online = runs[f"A_tdim_err{level}"][metric]
                fixg = runs[f"RED21_tdim_err{level}"][metric]
                effects.append(100 * (fixg / online - 1))
            rows.append((f"{trajectory}  {angle:g}$^\\circ$", *effects))
    row_y = np.arange(len(rows))[::-1]
    for yi, (_, z_value, ate_value) in zip(row_y, rows):
        ax.hlines(yi, min(z_value, ate_value), max(z_value, ate_value),
                  color=FAINT, lw=1.2, zorder=2)
    ate_artist = ax.scatter([row[2] for row in rows], row_y, s=26, marker="D",
               facecolor="white", edgecolor=INK, linewidth=0.9,
               zorder=3, label="ATE")
    z_artist = ax.scatter([row[1] for row in rows], row_y, s=17, marker="o",
               facecolor=COLORS["RED21"], edgecolor="white", linewidth=0.35,
               zorder=4, label="RMSE$_z$")
    ax.axhline(2.5, color=GRID, lw=0.65, zorder=1)
    ax.set_xlabel("FixG relative to Online [%]")
    ax.set_yticks(row_y, [row[0] for row in rows])
    ax.set_xlim(-5.5, 3.2)
    ax.set_xticks((-5, -2.5, 0, 2.5))
    ax.set_ylim(-0.65, 5.65)
    panel_title(ax, "c", "No monotonic cost through $2^\\circ$")
    ax.legend((z_artist, ate_artist), ("RMSE$_z$", "ATE"),
              frameon=False, ncol=2, loc="lower left", handlelength=0.9,
              columnspacing=0.75, borderaxespad=0.15, fontsize=5.4)
    fig.subplots_adjust(left=0.18, right=0.90, bottom=0.105, top=0.965,
                        hspace=0.62)
    save(fig, "fig_imuweight")


def fig_direction():
    """Added direction observations: non-monotonic nominal response and failure boundary."""
    data = direction_summary()
    fig = plt.figure(figsize=(7.15, 3.15))
    gs = fig.add_gridspec(
        2, 5, width_ratios=(1.30, 1.0, 1.0, 1.0, 1.0),
        height_ratios=(1.0, 1.02), hspace=0.52, wspace=0.70,
    )
    ax_s = fig.add_subplot(gs[:, 0])
    ax_fg = fig.add_subplot(gs[0, 1:3])
    ax_ge = fig.add_subplot(gs[0, 3:])
    ax_drop = fig.add_subplot(gs[1, 1:])

    # a: intervention schematic. It distinguishes a fixed state from an added
    # measurement without pretending that either observes height or velocity.
    ax_s.set_axis_off()
    ax_s.set_xlim(0, 1)
    ax_s.set_ylim(0, 1)
    panel_title(ax_s, "a", "What the factor adds")
    boxes = (
        (0.08, 0.80, 0.84, 0.12, "AHRS quaternion", NEUTRAL_FILL, INK),
        (0.08, 0.58, 0.84, 0.13, r"body down $\hat d_k^b$", HERO_FILL, HERO),
        (0.08, 0.34, 0.84, 0.15, r"$r_d=\mathrm{Log}_{S^2}(\hat d_k^b,R_k^Tg)$", VIOLET_FILL, VIOLET),
    )
    for x, y, w, h, label, face, edge in boxes:
        patch = FancyBboxPatch(
            (x, y), w, h, boxstyle="round,pad=0.012,rounding_size=0.025",
            facecolor=face, edgecolor=edge, linewidth=0.85,
        )
        ax_s.add_patch(patch)
        ax_s.text(x + w / 2, y + h / 2, label, ha="center", va="center",
                  fontsize=6.2, color=INK)
    for start, end in (((0.50, 0.80), (0.50, 0.71)), ((0.50, 0.58), (0.50, 0.49))):
        ax_s.annotate("", xy=end, xytext=start,
                      arrowprops={"arrowstyle": "-|>", "lw": 0.75, "color": MUTED})
    ax_s.text(0.50, 0.26, "one factor per\nLiDAR correction", ha="center",
              va="center", fontsize=5.9, color=MUTED)
    ax_s.plot((0.13, 0.87), (0.17, 0.17), color=GRID, lw=0.7)
    ax_s.text(0.13, 0.11, r"FG: $g$ fixed", ha="left", va="center",
              fontsize=6.1, color=INK, fontweight=700)
    ax_s.text(0.13, 0.045, r"GE: $g\in S^2$ online", ha="left", va="center",
              fontsize=6.1, color=HERO, fontweight=700)

    # b,c: nominal dose response. Dataset uses color; metric uses marker and
    # line style, so the figure remains interpretable in grayscale.
    sigmas = np.asarray((0.5, 2.0, 5.0))
    levels = ("s0p5", "s2", "s5")
    sequence_style = ((data["nominal"][0], "Hall05", INK),
                      (data["nominal"][1], "TUHH", HERO))
    for panel, (ax, variant, title) in enumerate((
        (ax_fg, "FG-BA", "Fixed $g$: a weight-sensitive response"),
        (ax_ge, "GE-BA", "Online $g$: no nominal pose gain"),
    )):
        ax.axhspan(-5, 5, color=PAPER, zorder=0)
        ax.axhline(0, color=INK, lw=0.72, zorder=1)
        horizontal_guides(ax, (-5, 5))
        for entry, label, color in sequence_style:
            z = [entry["runs"][f"{variant}_{level}"]["delta_rmse_z_pct_vs_off"]
                 for level in levels]
            ate = [entry["runs"][f"{variant}_{level}"]["delta_ate_pct_vs_off"]
                   for level in levels]
            ax.plot(sigmas, z, color=color, marker="o", ms=3.8, lw=1.05,
                    markerfacecolor=color, markeredgecolor="white",
                    markeredgewidth=0.35)
            ax.plot(sigmas, ate, color=color, marker="D", ms=3.4, lw=0.95,
                    ls=(0, (3, 2)), markerfacecolor="white",
                    markeredgewidth=0.85)
        ax.set_xticks(sigmas, ("0.5\nstrong", "2", "5\nweak"))
        ax.set_ylabel("factor relative to off [%]")
        ax.set_xlim(0.15, 5.35)
        panel_title(ax, "bc"[panel], title)
    ax_fg.set_ylim(-10.0, 5.0)
    ax_fg.set_yticks((-10, -5, 0, 5))
    ax_ge.set_ylim(-3.5, 5.0)
    ax_ge.set_yticks((-3, 0, 3))
    ax_ge.text(0.97, 0.92, "Hall05", transform=ax_ge.transAxes, ha="right",
               va="top", fontsize=5.8, color=INK)
    ax_ge.text(0.97, 0.80, "TUHH", transform=ax_ge.transAxes, ha="right",
               va="top", fontsize=5.8, color=HERO)
    ax_ge.text(0.97, 0.68, r"$\circ$ RMSE$_z$", transform=ax_ge.transAxes,
               ha="right", va="top", fontsize=5.7, color=MUTED)
    ax_ge.text(0.97, 0.56, r"$\diamond$ ATE", transform=ax_ge.transAxes,
               ha="right", va="top", fontsize=5.7, color=MUTED)

    # d: categorical operating map avoids compressing the replicated +500%
    # failure onto the same linear response axis as the small nominal effects.
    panel_title(ax_drop, "d", "Long gaps turn the same factor into a recovery hazard")
    ax_drop.set_xlim(0, 3)
    ax_drop.set_ylim(0, 4)
    rows = ("FG  RMSE$_z$", "FG  ATE", "GE  RMSE$_z$", "GE  ATE")
    ax_drop.set_yticks(np.arange(3.5, -0.5, -1), rows)
    ax_drop.set_xticks((0.5, 1.5, 2.5), ("2 s / 20 s", "3 s / 20 s", "5 s / 20 s"))
    ax_drop.tick_params(axis="both", length=0)
    for spine in ax_drop.spines.values():
        spine.set_visible(False)
    drop2 = data["dropout"][0]["runs"]
    drop5 = data["dropout"][2]
    ge5 = drop5["repeatability"]["GE-BA"]
    cell_text = (
        (f"{drop2['FG-BA_s2']['delta_rmse_z_pct_vs_off']:+.1f}%", "not\nidentifiable",
         f"{drop5['runs']['FG-BA_s2']['delta_rmse_z_pct_vs_off']:+.1f}%"),
        (f"{drop2['FG-BA_s2']['delta_ate_pct_vs_off']:+.1f}%", "not\nidentifiable",
         f"{drop5['runs']['FG-BA_s2']['delta_ate_pct_vs_off']:+.1f}%"),
        (f"{drop2['GE-BA_s2']['delta_rmse_z_pct_vs_off']:+.1f}%", "not\nidentifiable",
         f"+{ge5['delta_rmse_z_pct_range'][0]:.0f}--{ge5['delta_rmse_z_pct_range'][1]:.0f}%"),
        (f"{drop2['GE-BA_s2']['delta_ate_pct_vs_off']:+.1f}%", "not\nidentifiable",
         f"+{ge5['delta_ate_pct_range'][0]:.0f}--{ge5['delta_ate_pct_range'][1]:.0f}%"),
    )
    cell_values = (
        (drop2["FG-BA_s2"]["delta_rmse_z_pct_vs_off"], None,
         drop5["runs"]["FG-BA_s2"]["delta_rmse_z_pct_vs_off"]),
        (drop2["FG-BA_s2"]["delta_ate_pct_vs_off"], None,
         drop5["runs"]["FG-BA_s2"]["delta_ate_pct_vs_off"]),
        (drop2["GE-BA_s2"]["delta_rmse_z_pct_vs_off"], None,
         np.mean(ge5["delta_rmse_z_pct_range"])),
        (drop2["GE-BA_s2"]["delta_ate_pct_vs_off"], None,
         np.mean(ge5["delta_ate_pct_range"])),
    )
    for row in range(4):
        for col in range(3):
            value = cell_values[row][col]
            if value is None:
                face, edge, hatch, text_color = NEUTRAL_FILL, FAINT, "///", MUTED
            elif value < -0.5:
                strength = min(1.0, abs(value) / 10.0)
                face, edge, hatch, text_color = (0.91 - 0.22 * strength, 0.96,
                                                  0.96 - 0.12 * strength), HERO, None, INK
            elif value > 0.5:
                strength = min(1.0, value / 15.0)
                face, edge, hatch = (0.98, 0.91 - 0.26 * strength,
                                     0.91 - 0.26 * strength), ACCENT, None
                text_color = "white" if value > 50 else INK
            else:
                face, edge, hatch, text_color = QUIET_FILL, GRID, None, MUTED
            rect = plt.Rectangle((col + 0.04, 3 - row + 0.06), 0.92, 0.88,
                                 facecolor=face, edgecolor=edge, linewidth=0.7,
                                 hatch=hatch)
            ax_drop.add_patch(rect)
            ax_drop.text(col + 0.50, 3.50 - row, cell_text[row][col],
                         ha="center", va="center", fontsize=6.2,
                         color=text_color, fontweight=700 if value is not None and value > 50 else 500)
    fig.subplots_adjust(left=0.045, right=0.995, bottom=0.12, top=0.91)
    save(fig, "fig_direction")


def dropout_window_summary():
    return json.loads((ROOT / "report" / "dropout_windows.json").read_text())


def matched_ape_summary():
    path = ROOT / "report" / "matched_ape.json"
    if not path.exists():
        raise FileNotFoundError(
            "missing report/matched_ape.json; run scripts/collect_matched_ape.py"
        )
    data = json.loads(path.read_text())
    if (data.get("schema_version", 0) < 1 or
            data.get("status") != "complete_existing_results_only"):
        raise RuntimeError("matched APE report is not in its audited final state")
    for platform in ("vehicle", "handheld"):
        trajectory = data.get("trajectories", {}).get(platform, {})
        for condition in ("clean", "dropout"):
            block = trajectory.get(condition, {})
            if block.get("repeat_count") != 3 or not block.get(
                    "metric_crosscheck", False):
                raise RuntimeError(
                    f"matched APE {platform}/{condition} failed its data gates"
                )
    return data


def fig_teaser_rebuilt():
    """Conceptual entry point; paths illustrate logic, not measured trajectories."""
    cells = {e["sequence"]: e["cells"] for e in
             strengthening_summary()["liosam_dropout_weights"]["sequences"]}
    for seq, variant, sign in (("hall05", "FG-BA", -1),
                               ("tuhh_day04", "GE-BA", 1)):
        for metric in ("delta_rmse_z_pct_vs_off", "delta_ate_pct_vs_off"):
            if sign*cells[seq][variant+"_s2"][metric]["median"] <= 0:
                raise ValueError("teaser direction-factor example no longer supported")
    S = summary()
    n = sum("A" in S[s]["runs"] and "RED21" in S[s]["runs"] for s, _ in CORE)
    if n != len(CORE):
        raise ValueError("incomplete nominal teaser evidence")
    fig, ax = plt.subplots(figsize=(3.484, 4.00))
    ax.set(xlim=(0, 1), ylim=(0, 1)); ax.axis("off")

    def text(x, y, label, *, size=8, color=INK, weight="normal",
             ha="left", va="center"):
        return ax.text(x, y, label, fontsize=size, color=color,
                       fontweight=weight, ha=ha, va=va)

    def arrow(start, end, color=INK, **kwargs):
        ax.add_patch(FancyArrowPatch(start, end, arrowstyle="-|>",
                     mutation_scale=8, lw=1, color=color, **kwargs))

    def heading(y, letter, title):
        text(.02, y, letter, size=9, weight="bold")
        text(.08, y, title, size=8.7, weight="bold")

    def pulses(y, gap=None):
        ticks = np.linspace(.10, .91, 22)
        if gap:
            ticks = ticks[(ticks < gap[0]) | (ticks >= gap[1])]
        ax.vlines(ticks, y-.012, y+.012, color=MUTED, lw=.8)

    def paired(x, y):
        ax.plot(x, y, color=HERO, lw=2)
        ax.plot(x, y, color=INK, lw=1.25, ls=(0, (4, 3)))

    text(.97, .988, "SCHEMATIC", size=6.8, color=MUTED, ha="right")
    heading(.945, "a", "Gravity can move without changing pose")
    text(.10, .902, "continuous LiDAR corrections", size=7.7, color=MUTED)
    pulses(.866)
    x = np.linspace(.10, .91, 150)
    y = .803 + .019*np.sin((x-.10)*7)
    paired(x, y)
    # Two distinct directions with visible shafts at single-column print size.
    ax.add_patch(plt.Circle((.13, .728), .035, fill=False, ec=GRID, lw=.7))
    for dx, color in ((-.025, MUTED), (.025, HERO)):
        ax.add_patch(FancyArrowPatch((.13, .754), (.13+dx, .706),
                     arrowstyle="-|>", mutation_scale=6.5, lw=.9,
                     color=color, shrinkA=0, shrinkB=0))
    text(.19, .738, "changing g", size=7.7, color=MUTED)
    text(.94, .738, f"{n} sequences: little pose effect", size=7.7, ha="right")
    ax.plot((.08, .18), (.687, .687), color=HERO, lw=1.9)
    text(.20, .687, "Online", size=7.7)
    ax.plot((.49, .59), (.687, .687), color=INK, lw=1.25, ls=(0, (4, 3)))
    text(.61, .687, "FixG", size=7.7)

    heading(.625, "b", "The difference can emerge at scan return")
    gap = (.32, .70)
    # The strip represents only sensor absence, not estimator uncertainty.
    ax.add_patch(plt.Rectangle((gap[0], .385), gap[1]-gap[0], .165,
                              fc=ACCENT_FILL, ec="none", zorder=0))
    text(.51, .575, "multi-second LiDAR gap", size=8, color=ACCENT, ha="center")
    pulses(.538, gap)
    x = np.linspace(.10, gap[1], 140)
    y = .449 + .012*np.sin((x-.10)*6)
    paired(x, y)
    post = np.linspace(gap[1], .92, 70)
    u = (post-gap[1])/(.92-gap[1])
    ax.plot(post, y[-1]-.038*u, color=HERO, lw=2)
    ax.plot(post, y[-1]+.085*u**1.2, color=INK, lw=1.25, ls=(0, (4, 3)))
    ax.vlines(gap[1], .384, .553, color=MUTED, lw=.8)
    ax.scatter([gap[1]], [y[-1]], s=26, fc="white", ec=INK, zorder=5)
    text(.48, .407, "shared propagation", size=7.7, ha="center")
    arrow((.80, .345), (gap[1]+.005, .394), MUTED)
    text(.93, .327, "first recovered scan", size=7.7, color=MUTED, ha="right")
    text(.08, .355, "matched state at gap onset", size=7.7, color=MUTED)
    text(.08, .299, "Recovery depends on the trajectory.", size=8)

    heading(.236, "c", "A direction constraint is not a height prior")
    # A minimal factor graph: orientation and direction, with no height node.
    ax.plot((.12, .36), (.153, .153), color=MUTED, lw=.9)
    ax.scatter([.12], [.153], s=200, fc="white", ec=INK, lw=.9, zorder=3)
    ax.scatter([.25], [.153], s=85, marker="s", fc=HERO_FILL, ec=HERO, zorder=3)
    text(.12, .153, r"$R_k$", ha="center", size=8)
    text(.385, .153, r"$g$", ha="center", size=9)
    text(.25, .197, "same-IMU direction", size=7.5, ha="center")
    arrow((.25, .183), (.25, .169), MUTED)
    text(.08, .098, "roll / pitch consistency", size=7.6, color=MUTED)
    ax.plot((.47, .47), (.085, .20), color=GRID, lw=.7)
    text(.52, .176, "Hall05 / FixG", size=7.8)
    text(.94, .146, "z error ↓", size=8, color=HERO, ha="right")
    text(.52, .106, "TUHH / Online", size=7.8)
    text(.94, .076, "z error ↑", size=8, color=ACCENT, ha="right")
    text(.50, .020, "Better direction agreement need not reduce z drift.",
         size=7.8, ha="center")
    fig.subplots_adjust(left=.015, right=.985, bottom=.01, top=.99)
    save(fig, "fig_teaser")


def fig_design_rebuilt():
    manifest, xyz, intensity = design_pointcloud_summary()
    interventions = manifest["interventions"]
    counts = manifest["counts"]
    visual = manifest["visualization"]

    fig = plt.figure(figsize=(3.35, 3.55))
    gs = fig.add_gridspec(
        4, 3, height_ratios=(1.34, 0.32, 0.82, 0.24),
        hspace=0.14, wspace=0.06)
    ax = fig.add_subplot(gs[0, :])
    ax.set_axis_off(); ax.set_xlim(0, 2.0); ax.set_ylim(0, 1.58)
    panel_title(ax, "a", "Two orthogonal state interventions")
    ax.text(0.73, 1.42, "$g$ online", ha="center", fontsize=7.0, color=MUTED)
    ax.text(1.51, 1.42, "$g$ fixed", ha="center", fontsize=7.0, color=MUTED)
    ax.text(0.06, 1.00, "$b_a$ online", rotation=90, va="center", fontsize=7.0, color=MUTED)
    ax.text(0.06, 0.37, "$b_a$ fixed", rotation=90, va="center", fontsize=7.0, color=MUTED)
    cells = ((0.38, 0.78, "Online", "23D", INK, NEUTRAL_FILL),
             (1.16, 0.78, "FixG", "21D", HERO, HERO_FILL),
             (0.38, 0.14, "FixBa", "20D", MUTED, NEUTRAL_FILL),
             (1.16, 0.14, "FixG+Ba", "18D", ACCENT, ACCENT_FILL))
    for x, y0, label, dim, color, face in cells:
        ax.add_patch(plt.Rectangle((x, y0), 0.62, 0.44, facecolor=face,
                                   edgecolor=color, lw=1.0))
        ax.text(x + 0.31, y0 + 0.28, label, ha="center", va="center",
                fontsize=7.5, fontweight=700, color=color)
        ax.text(x + 0.31, y0 + 0.11, dim, ha="center", fontsize=6.8, color=MUTED)
    ax.text(0.38, -0.02, "extrinsics fixed identically in every cell",
            fontsize=6.9, color=INK,
            bbox={"facecolor": "white", "edgecolor": GRID, "pad": 2.0})

    title_ax = fig.add_subplot(gs[1, :])
    title_ax.set_axis_off()
    title_ax.text(-0.01, 0.80, "b", transform=title_ax.transAxes,
                  ha="right", va="center", fontsize=8.0,
                  fontweight=700, color=INK)
    title_ax.text(0.01, 0.80, "FAST-LIO ROS1 RViz scan, three interventions",
                  transform=title_ax.transAxes, ha="left", va="center",
                  fontsize=7.6, fontweight=700, color=INK)

    radius = np.linalg.norm(xyz[:, :2], axis=1)
    azimuth = np.abs(np.arctan2(xyz[:, 1], xyz[:, 0]))
    display_mask = (
        (radius < visual["common_xy_limit_m"])
        & (xyz[:, 2] > visual["z_limits_m"][0])
        & (xyz[:, 2] < visual["z_limits_m"][1])
    )
    display_indices = np.flatnonzero(display_mask)
    if len(display_indices) > visual["max_display_points"]:
        rng = np.random.default_rng(visual["random_seed"])
        display_indices = np.sort(rng.choice(
            display_indices, visual["max_display_points"], replace=False))
    masks = (
        np.ones(len(xyz), dtype=bool),
        radius < interventions["range_limit_m"],
        azimuth < np.deg2rad(interventions["fov_half_angle_deg"]),
    )
    subtitles = (
        "full scan",
        f"{100 * counts['range_retained'] / counts['finite_points']:.0f}% retained",
        f"{100 * counts['fov_retained'] / counts['finite_points']:.0f}% retained",
    )
    titles = (
        "nominal",
        f"range < {interventions['range_limit_m']:.0f} m",
        f"FoV ±{interventions['fov_half_angle_deg']:.0f}°",
    )
    renderer = visual["renderer"]
    title_ax.text(0.01, 0.18, "Intensity channel", transform=title_ax.transAxes,
                  ha="left", va="center", fontsize=6.1, color=MUTED)
    rainbow_ax = title_ax.inset_axes((0.245, 0.105, 0.34, 0.20))
    rainbow_values = np.linspace(0.0, 1.0, 512)
    rainbow_rgb = rviz_rainbow_colors(
        rainbow_values, 0.0, 1.0,
        invert=renderer["invert_rainbow"])
    rainbow_edges = np.linspace(0.0, 1.0, rainbow_values.size + 1)
    rainbow_ax.pcolormesh(
        rainbow_edges, (0.0, 1.0), rainbow_values[np.newaxis, :],
        shading="flat",
        cmap=matplotlib.colors.ListedColormap(rainbow_rgb),
        vmin=0.0, vmax=1.0, rasterized=False,
    )
    rainbow_ax.set_xticks((0, 1), ("low", "high"))
    rainbow_ax.xaxis.set_ticks_position("top")
    rainbow_ax.tick_params(axis="x", labelsize=5.6, length=0, pad=0.5)
    rainbow_ax.set_yticks([])
    for spine in rainbow_ax.spines.values():
        spine.set_color(GRID); spine.set_linewidth(0.55)
    title_ax.text(0.62, 0.18, "linear · auto bounds / cloud",
                  transform=title_ax.transAxes, ha="left", va="center",
                  fontsize=5.9, color=MUTED)
    limit = visual["common_xy_limit_m"]
    for column, (mask, title, subtitle) in enumerate(zip(masks, titles, subtitles)):
        cloud_ax = fig.add_subplot(gs[2, column])
        selected = display_indices[mask[display_indices]]
        points = xyz[selected]
        point_intensity = intensity[selected]
        admitted_intensity = intensity[mask]
        intensity_min = float(np.min(admitted_intensity))
        intensity_max = float(np.max(admitted_intensity))
        point_colors = rviz_rainbow_colors(
            point_intensity, intensity_min, intensity_max,
            invert=renderer["invert_rainbow"])
        color = INK if column == 0 else HERO
        cloud_ax.set_facecolor("#000000")
        cloud_ax.scatter(points[:, 0], points[:, 1], s=0.18,
                         c=point_colors, alpha=renderer["alpha"],
                         linewidths=0, rasterized=False)
        cloud_ax.scatter([0], [0], s=11, marker="^", facecolor="white",
                         edgecolor=ACCENT, linewidth=0.75, zorder=5)
        cloud_ax.set_xlim(-limit, limit); cloud_ax.set_ylim(-limit, limit)
        cloud_ax.set_aspect("equal"); cloud_ax.set_xticks([]); cloud_ax.set_yticks([])
        for spine in cloud_ax.spines.values():
            spine.set_visible(True); spine.set_color(GRID); spine.set_linewidth(0.55)
        cloud_ax.set_title(title, fontsize=7.2, fontweight=700,
                           color=color, pad=2.0)
        bound_text = f"{subtitle} · I {intensity_min:.0f}–{intensity_max:.0f}"
        cloud_ax.text(0.5, 0.025, bound_text, transform=cloud_ax.transAxes,
                      ha="center", va="bottom", fontsize=5.55, color="white",
                      bbox={"facecolor": "black", "edgecolor": "none",
                            "alpha": 0.72, "pad": 0.8})

    drop_ax = fig.add_subplot(gs[3, :])
    drop_ax.set_axis_off(); drop_ax.set_xlim(0, 20); drop_ax.set_ylim(0, 1)
    drop_ax.text(0, 0.84, "whole-message dropout", ha="left", va="center",
                 fontsize=7.1, fontweight=700, color=ACCENT)
    drop_ax.text(20, 0.84, "1–5 s: no LiDAR messages", ha="right", va="center",
                 fontsize=6.8, color=ACCENT)
    drop_ax.hlines(0.25, 0.0, 20.0, color=GRID, lw=0.8)
    gap_start, gap_end = 9.2, 13.8
    drop_ax.add_patch(plt.Rectangle((gap_start, 0.04), gap_end-gap_start, 0.42,
                                    facecolor=ACCENT_FILL, edgecolor=ACCENT,
                                    lw=0.65, hatch="////"))
    times = np.arange(0.2, 19.9, 0.55)
    times = times[(times < gap_start) | (times > gap_end)]
    drop_ax.vlines(times, 0.10, 0.40, color=HERO, lw=0.8)
    fig.subplots_adjust(left=0.055, right=0.99, bottom=0.045, top=0.95)
    save(fig, "fig_design")


def fig_factorial_rebuilt():
    S = summary(); LS = liosam_summary()
    E = equivalence_sensitivity_summary()
    fig = plt.figure(figsize=(3.35, 5.95))
    gs = fig.add_gridspec(4, 1, height_ratios=(1.12, 1.20, 0.82, 0.82),
                          hspace=0.78)
    ax_ci = fig.add_subplot(gs[0, 0])
    trace_gs = gs[1, 0].subgridspec(2, 1, hspace=0.08)
    ax_trace_z = fig.add_subplot(trace_gs[0, 0])
    ax_trace_g = fig.add_subplot(trace_gs[1, 0], sharex=ax_trace_z)
    traj_gs = gs[2, 0].subgridspec(2, 4, height_ratios=(0.22, 0.78),
                                    hspace=0.02, wspace=0.16)
    ax_traj_title = fig.add_subplot(traj_gs[0, :])
    traj_axes = [fig.add_subplot(traj_gs[1, i]) for i in range(4)]
    ax_lio = fig.add_subplot(gs[3, 0])

    def evidence_title(ax, letter, title, y=1.035):
        # Use the same text anchors even for the trajectory-only title axis.
        ax.text(-0.045, y, letter, transform=ax.transAxes, ha="right",
                va="bottom", fontsize=8.0, fontweight=700, color=INK)
        ax.text(0.015, y, title, transform=ax.transAxes, ha="left",
                va="bottom", fontsize=7.8, fontweight=700, color=INK)

    def ci(metric):
        ratios = np.asarray([S[s]["runs"]["RED21"][metric] / S[s]["runs"]["A"][metric]
                             for s, _ in CORE])
        lr = np.log(ratios); half = stats.t.ppf(0.95, len(lr)-1) * stats.sem(lr)
        return 100 * (np.exp((lr.mean()-half, lr.mean(), lr.mean()+half)) - 1)
    formal_margin = E["margins"]["formal_pre_specified_pct"]
    strict_margin = E["margins"]["posthoc_sensitivity_pct"]
    ax_ci.axvspan(-formal_margin, formal_margin, color=NEUTRAL_FILL)
    ax_ci.axvspan(-strict_margin, strict_margin, color=HERO_FILL)
    ax_ci.axvline(0, color=INK, lw=0.8)
    for yi, metric, label, marker in ((1, "rmse_z_m", "RMSE$_z$", "o"),
                                      (0, "ate_rmse_m", "ATE", "D")):
        sequence_effects = np.asarray([
            100 * (S[s]["runs"]["RED21"][metric] /
                   S[s]["runs"]["A"][metric] - 1)
            for s, _ in CORE
        ])
        offsets = np.linspace(-0.20, 0.20, len(sequence_effects))
        ax_ci.scatter(sequence_effects, yi + offsets, s=10,
                      facecolor="white", edgecolor=MUTED, linewidth=0.65,
                      zorder=2)
        lo, mid, hi = ci(metric)
        ax_ci.errorbar(mid, yi, xerr=[[mid-lo], [hi-mid]], color=HERO,
                       marker=marker, ms=6, markerfacecolor="white", lw=1.6,
                       capsize=3, markeredgewidth=1.2, zorder=4)
        ax_ci.text(7.75, yi - 0.40, f"{mid:+.2f} [{lo:+.2f}, {hi:+.2f}]",
                   ha="right", va="center", fontsize=7.5, color=HERO,
                   bbox={"facecolor": "white", "edgecolor": "none",
                         "pad": 0.4, "alpha": 0.88})
    ax_ci.set_yticks((1,0), ("vertical", "3D position")); ax_ci.set_xlim(-7.5, 8.0)
    ax_ci.set_xticks((-5,0,5)); ax_ci.set_ylim(-0.65,1.65)
    ax_ci.set_xlabel("FixG relative to Online [%, 90% CI]")
    evidence_title(ax_ci, "a", f"Paired FixG effect ({len(CORE)} sequences)")
    ax_ci.text(-4.75, 1.5, "±5% prespecified · ±2% sensitivity",
               fontsize=7.5, color=MUTED)

    # A paired, representative real-sequence trace makes the distinction between
    # state motion and trajectory utility visible. Population inference remains
    # in panel a; fail hard if the audited pair is unavailable or misaligned.
    trace_report = mechanism_trace_summary()
    trace_seq = trace_report["sequence"]
    trace_paths = {
        label: RESULTS / trace_seq / run / "state_log.csv"
        for label, run in trace_report["runs"].items()
    }
    for path in trace_paths.values():
        if not path.exists():
            raise FileNotFoundError(f"mechanism trace missing: {path}")
    online = pd.read_csv(trace_paths["Online"])
    fixg = pd.read_csv(trace_paths["FixG"])
    required = {"t", "pz", "gx", "gy", "gz"}
    if not required.issubset(online.columns) or not required.issubset(fixg.columns):
        raise ValueError("mechanism trace lacks required state fields")
    if len(online) != len(fixg) or not np.allclose(
            online["t"].to_numpy(), fixg["t"].to_numpy(), atol=1e-9):
        raise ValueError("Online/FixG mechanism traces are not timestamp-paired")
    t_min = (online["t"].to_numpy() - online["t"].iloc[0]) / 60.0
    z_online = online["pz"].to_numpy() - online["pz"].iloc[0]
    z_fixg = fixg["pz"].to_numpy() - fixg["pz"].iloc[0]
    gravity = online[["gx", "gy", "gz"]].to_numpy()
    gravity /= np.linalg.norm(gravity, axis=1, keepdims=True)
    gravity_angle = np.degrees(np.arccos(np.clip(gravity @ gravity[0], -1, 1)))
    calculated = {
        "online_gravity_wander_max_deg": float(np.max(gravity_angle)),
        "paired_z_separation_max_m": float(np.max(np.abs(z_online - z_fixg))),
    }
    metrics = trace_report["metrics"]
    for key, value in calculated.items():
        if not np.isclose(value, metrics[key], rtol=0, atol=1e-10):
            raise ValueError(
                f"stale mechanism-trace report for {key}; rerun "
                "scripts/collect_mechanism_trace.py"
            )
    max_g_angle = float(metrics["online_gravity_wander_max_deg"])
    max_z_sep = float(metrics["paired_z_separation_max_m"])
    trace_stride = max(1, len(t_min) // 1100)

    ax_trace_z.plot(t_min[::trace_stride], z_online[::trace_stride],
                    color=HERO, lw=1.05, label="Online")
    ax_trace_z.plot(t_min[::trace_stride], z_fixg[::trace_stride],
                    color=INK, lw=0.85, ls=(0, (3, 2)), label="FixG")
    ax_trace_z.set_ylabel("relative z [m]", labelpad=2)
    ax_trace_z.tick_params(axis="x", labelbottom=False)
    ax_trace_z.grid(axis="y", color=GRID, lw=0.45)
    ax_trace_z.legend(frameon=False, ncol=1, loc="upper left",
                      fontsize=7.5, handlelength=1.5,
                      borderaxespad=0.15)
    ax_trace_z.text(0.99, 0.88, f"max paired |$\\Delta z$| = {max_z_sep:.2f} m",
                    transform=ax_trace_z.transAxes, ha="right", va="top",
                    fontsize=7.5, color=INK,
                    bbox={"facecolor": "white", "edgecolor": "none", "pad": 0.5,
                          "alpha": 0.88})
    evidence_title(ax_trace_z, "b", "Vertical path and gravity direction")

    ax_trace_g.plot(t_min[::trace_stride], gravity_angle[::trace_stride],
                    color=HERO, lw=1.0)
    ax_trace_g.fill_between(t_min[::trace_stride], 0,
                            gravity_angle[::trace_stride], color=HERO_FILL,
                            linewidth=0)
    ax_trace_g.axhline(0, color=INK, lw=0.65, ls=(0, (3, 2)))
    ax_trace_g.set_ylabel(r"$\Delta\mathbf{g}$ [$^\circ$]", labelpad=2)
    ax_trace_g.set_xlabel("time [min]", labelpad=1)
    ax_trace_g.set_ylim(-0.15, max_g_angle * 1.16)
    ax_trace_g.yaxis.set_major_locator(
        matplotlib.ticker.MaxNLocator(nbins=3, integer=True))
    ax_trace_g.grid(axis="y", color=GRID, lw=0.45)
    ax_trace_g.text(0.99, 0.82, f"Online max = {max_g_angle:.1f}°",
                    transform=ax_trace_g.transAxes, ha="right", va="top",
                    fontsize=7.5, color=HERO)

    ax_traj_title.set_axis_off()
    evidence_title(ax_traj_title, "c", "Representative paths", y=0.55)
    trajectories = (
        ("ntu_day_10_os1", "MCD\nvehicle"),
        ("tuhh_day_04_os1", "MCD\nhandheld"),
        ("IndoorOffice1", "TIERS\nquadruped"),
        ("hall_05_run", "M2DGR\nground robot"),
    )
    for ax, (seq, label) in zip(traj_axes, trajectories):
        path = RESULTS / seq / "A" / "state_log.csv"
        if not path.exists():
            raise FileNotFoundError(f"representative trajectory missing: {path}")
        data = pd.read_csv(path, usecols=["px", "py"]).dropna().to_numpy()
        if len(data) < 2:
            raise ValueError(f"representative trajectory is empty: {path}")
        stride = max(1, len(data) // 900)
        xy = data[::stride] - data[0]
        ax.plot(xy[:, 0], xy[:, 1], color=HERO, lw=0.85,
                solid_capstyle="round")
        ax.scatter(xy[0, 0], xy[0, 1], s=7, facecolor=INK,
                   edgecolor="white", linewidth=0.3, zorder=3)
        ax.scatter(xy[-1, 0], xy[-1, 1], s=9, marker="D",
                   facecolor="white", edgecolor=HERO, linewidth=0.8, zorder=3)
        length = float(S[seq]["gt"]["path_len_m"])
        length_label = f"{length / 1000:.2f} km" if length >= 1000 else f"{length:.0f} m"
        ax.text(0.5, -0.08, f"{label}\n{length_label}", transform=ax.transAxes,
                ha="center", va="top", fontsize=7.5, color=INK,
                linespacing=1.05)
        ax.set_aspect("equal", adjustable="datalim")
        ax.margins(0.08)
        ax.set_axis_off()

    entries = LS["sequences"]
    lio_labels = {
        "m2dgr-hall05": "Hall05",
        "mcd_tuhh_day_04": "TUHH d04",
        "ntu_day_02": "NTU d02",
        "tuhh_night_09": "TUHH n09",
    }
    labels=[]
    for i,e in enumerate(entries):
        labels.append(lio_labels[e["sequence"]])
        r=e["runs"]; zv=100*(r["GE-BA"]["rmse_z_m"]/r["FG-BA"]["rmse_z_m"]-1); av=100*(r["GE-BA"]["ate_rmse_m"]/r["FG-BA"]["ate_rmse_m"]-1)
        ax_lio.hlines(i,min(zv,av),max(zv,av),color=GRID,lw=1.2)
        ax_lio.scatter(zv,i+.08,s=24,color=HERO,marker="o")
        ax_lio.scatter(av,i-.08,s=25,facecolor="white",edgecolor=INK,marker="D")
    ax_lio.axvline(0,color=INK,lw=.75); ax_lio.set_yticks(range(len(entries)),labels)
    ax_lio.set_xlim(-.7,.7); ax_lio.set_xticks((-.5,0,.5)); ax_lio.set_xlabel("GE-BA relative to FG-BA [%]")
    evidence_title(ax_lio, "d", "LIO-SAM state ablation")
    for ax in (ax_ci, ax_trace_z, ax_trace_g, ax_lio):
        ax.tick_params(axis="both", labelsize=7.5)
        for label in (ax.xaxis.label, ax.yaxis.label):
            label.set_size(7.5)
            label.set_weight("normal")
    fig.subplots_adjust(left=.20,right=.985,bottom=.075,top=.965)
    save(fig,"fig_factorial")


def fig_boundary_rebuilt():
    S = summary()
    APE = matched_ape_summary()
    fig = plt.figure(figsize=(3.35, 5.55))
    gs = fig.add_gridspec(3, 1, height_ratios=(1.0, 1.0, 0.94), hspace=0.82)
    axes = (fig.add_subplot(gs[0, 0]), fig.add_subplot(gs[1, 0]))
    for pi, (ax, prefix, seconds, title, ylim) in enumerate((
            (axes[0], "ntu_day_10", (0, 1, 2, 3, 5),
             "Vehicle: transition at 2–3 s", (-25, 135)),
            (axes[1], "tuhh_day_04", (0, 2, 3, 5),
             "Handheld: later response", (-8, 40)))):
        ax.axhline(0, color=INK, lw=0.75, ls=(0, (3, 2)))
        for metric, label, marker, color, ls in (
                ("rmse_z_m", "RMSE$_z$", "o", HERO, "-"),
                ("ate_rmse_m", "ATE", "D", INK, "--")):
            pts = []
            for sec in seconds:
                seq = f"{prefix}_os1" if sec == 0 else f"{prefix}_drop{sec}x20"
                runs = S[seq]["runs"]
                rep = prefix == "ntu_day_10" and sec in (2, 3)
                a = np.asarray(repeat_values(runs, "A", metric, rep))
                g = np.asarray(repeat_values(runs, "RED21", metric, rep))
                rr = g / np.median(a)
                pts.append((sec, np.median(rr), np.min(rr), np.max(rr)))
            p = np.asarray(pts)
            eff = 100 * (p[:, 1] - 1)
            ax.errorbar(p[:, 0], eff,
                        yerr=np.vstack((100 * (p[:, 1] - p[:, 2]),
                                        100 * (p[:, 3] - p[:, 1]))),
                        color=color, marker=marker, ms=4.4, mfc="white",
                        lw=1.2, ls=ls, capsize=2, label=label)
        ax.set_xticks(seconds)
        ax.set_ylim(*ylim)
        ax.set_xlabel("dropout per 20 s [s]")
        ax.set_ylabel("FixG relative to Online [%]")
        panel_title(ax, "ab"[pi], title)
    axes[1].legend(frameon=False, ncol=2, loc="upper left",
                   handlelength=1.1)

    # A paired trajectory-error view adds only the missing evidence: clean and
    # dropout histories begin identically, but their APE contrasts separate on
    # different time scales.  Each line is the median of three serial pairs;
    # bands are their full ranges.  No representative run is selected.
    ape_gs = gs[2, 0].subgridspec(1, 2, wspace=0.24)
    ape_axes = (
        fig.add_subplot(ape_gs[0, 0]),
        fig.add_subplot(ape_gs[0, 1]),
    )
    all_bounds = []
    for trajectory in APE["trajectories"].values():
        for condition in ("clean", "dropout"):
            for segment in trajectory[condition]["segments"]:
                all_bounds.extend(segment["range_low_m"])
                all_bounds.extend(segment["range_high_m"])
    low, high = min(all_bounds), max(all_bounds)
    padding = 0.08 * (high - low)
    horizon = float(APE["common_horizon_s"])
    x_ticks = np.arange(0.0, horizon + 1e-9, 50.0)

    for index, (ax, platform, name) in enumerate(zip(
            ape_axes, ("vehicle", "handheld"), ("Vehicle", "Handheld"))):
        trajectory = APE["trajectories"][platform]
        for gap in trajectory["dropout"]["gaps"]:
            ax.axvspan(gap["last_correction_s"], gap["first_return_s"],
                       color=ACCENT_FILL, lw=0, zorder=0)
        ax.axhline(0, color=INK, lw=0.65, zorder=1)
        ax.axvline(0, color=FAINT, lw=0.65, ls=(0, (2, 2)), zorder=1)
        for condition, label, color, linestyle in (
                ("clean", "continuous", MUTED, (0, (3, 2))),
                ("dropout", "dropout", ACCENT, "-")):
            first = True
            for segment in trajectory[condition]["segments"]:
                time = np.asarray(segment["time_s"])
                median = np.asarray(segment["median_m"])
                lower = np.asarray(segment["range_low_m"])
                upper = np.asarray(segment["range_high_m"])
                if condition == "dropout":
                    ax.fill_between(time, lower, upper, color=ACCENT,
                                    alpha=0.12, linewidth=0, zorder=2)
                ax.plot(time, median, color=color, lw=1.0, ls=linestyle,
                        label=label if first else None, zorder=3)
                first = False
        gap_name = trajectory["dropout_label"].replace("/20 s", " gaps")
        panel_title(ax, "cd"[index], f"{name} · {gap_name}")
        ax.set_xlim(-2.0, horizon)
        ax.set_ylim(low - padding, high + padding)
        ax.set_xticks(x_ticks)
        ax.set_xlabel("time after switch [s]", fontsize=6.0, labelpad=1)
        ax.tick_params(axis="both", labelsize=5.7)
        ax.grid(axis="y", color=GRID, lw=0.45)
        ax.text(0.98, 0.96,
                f"n={trajectory['dropout']['repeat_count']} pairs",
                transform=ax.transAxes, ha="right", va="top",
                fontsize=5.2, color=MUTED)
    ape_axes[0].set_ylabel(r"$\Delta$APE [m]", fontsize=6.0, labelpad=1)
    ape_axes[0].text(0.02, 0.05, ">0: FixG worse",
                     transform=ape_axes[0].transAxes, ha="left", va="bottom",
                     fontsize=5.15, color=MUTED)
    ape_axes[0].legend(frameon=False, ncol=2, loc="upper left",
                       bbox_to_anchor=(0.0, 0.88), fontsize=5.2,
                       handlelength=1.25, columnspacing=0.65,
                       borderaxespad=0)
    ape_axes[1].tick_params(axis="y", labelleft=False)
    fig.subplots_adjust(left=0.20, right=0.985, bottom=0.075, top=0.965)
    save(fig, "fig_boundary")


def fig_direction_rebuilt():
    """Single-column direction-factor counterexample with no redundant schematic."""
    from matplotlib.lines import Line2D

    data = direction_summary()
    fig = plt.figure(figsize=(3.35, 3.40))
    gs = fig.add_gridspec(2, 1, height_ratios=(0.94, 1.06), hspace=0.62)
    ax_sc = fig.add_subplot(gs[0, 0])
    bottom = gs[1, 0].subgridspec(1, 2, wspace=0.58)
    response_axes = [fig.add_subplot(bottom[0, i]) for i in range(2)]

    panel_title(ax_sc, "a", "Nominal direction-factor response")
    markers = {"FG-BA": "o", "GE-BA": "D"}
    trajectory_colors = {"m2dgr-hall05": HERO, "mcd-tuhh-day04": INK}
    for entry in data["nominal"]:
        color = trajectory_colors[entry["sequence"]]
        for variant in ("FG-BA", "GE-BA"):
            for level in ("s0p5", "s2", "s5"):
                run = entry["runs"][f"{variant}_{level}"]
                factor = run.get("direction_factor", {})
                residual_change = (
                    factor.get("median_post_residual_deg", 0) -
                    factor.get("median_pre_residual_deg", 0)
                )
                ax_sc.scatter(
                    residual_change, run["delta_rmse_z_pct_vs_off"],
                    s=28, marker=markers[variant], facecolor="white",
                    edgecolor=color, linewidth=1.0, zorder=3,
                )
    ax_sc.axhline(0, color=INK, lw=0.7)
    ax_sc.axvline(0, color=INK, lw=0.7, ls=(0, (3, 2)))
    ax_sc.set_xlim(-0.57, 0.035)
    ax_sc.set_ylim(-10, 5)
    ax_sc.set_xticks((-0.5, -0.25, 0.0))
    ax_sc.set_yticks((-10, -5, 0, 5))
    ax_sc.set_xlabel(r"post $-$ pre median residual [$^\circ$]", fontsize=7.6)
    ax_sc.set_ylabel("factor effect on RMSE$_z$ [%]", fontsize=7.6)
    ax_sc.tick_params(labelsize=7.4)
    ax_sc.grid(color=GRID, lw=0.45)
    handles = (
        Line2D([], [], marker="o", ls="", mfc="white", mec=HERO,
               mew=1.0, label="Hall05"),
        Line2D([], [], marker="o", ls="", mfc="white", mec=INK,
               mew=1.0, label="TUHH"),
        Line2D([], [], marker="o", ls="", mfc="white", mec=MUTED,
               mew=1.0, label="FixG"),
        Line2D([], [], marker="D", ls="", mfc="white", mec=MUTED,
               mew=1.0, label="Online"),
    )
    ax_sc.legend(handles=handles, frameon=False, ncol=2, loc="lower left",
                 columnspacing=1.0, handletextpad=0.4, borderaxespad=0.35,
                 fontsize=7.2)

    final = strengthening_summary()["liosam_dropout_weights"]["sequences"]
    cells = {entry["sequence"]: entry["cells"] for entry in final}
    for ax, sequence, title, letter in zip(response_axes,
            ("hall05", "tuhh_day04"), ("Hall05", "TUHH"), ("b", "c")):
        for variant, color in (("FG-BA", INK), ("GE-BA", HERO)):
            for key, marker, ls in (("delta_rmse_z_pct_vs_off", "o", "-"),
                                    ("delta_ate_pct_vs_off", "D", "--")):
                med, low, high = [], [], []
                for level in ("s0p5", "s2", "s5"):
                    stat = cells[sequence][variant+"_"+level][key]
                    med.append(stat["median"])
                    low.append(stat["range"][0]); high.append(stat["range"][1])
                med = np.asarray(med)
                ax.errorbar((.5, 2, 5), med,
                            yerr=[med-np.asarray(low), np.asarray(high)-med],
                            color=color, marker=marker, ls=ls, mfc="white",
                            ms=3.7, lw=1, capsize=2)
        ax.axhline(0, color=FAINT, lw=.7)
        ax.set_xscale("log")
        ax.set_xlim(.38, 6.4)
        ax.set_xticks((.5, 2, 5), ("0.5", "2", "5"))
        ax.xaxis.set_minor_locator(matplotlib.ticker.NullLocator())
        ax.set_xlabel(r"$\sigma_d$ [°]", fontsize=7.4)
        ax.set_ylim((-105, 10) if sequence == "hall05" else (-110, 650))
        ax.tick_params(labelsize=7)
        ax.grid(axis="y", color=GRID, lw=.4)
        panel_title(ax, letter, title + " / 5-s gaps")
    response_axes[0].set_ylabel("paired error change [%]", fontsize=7.4)
    for ax in (ax_sc, *response_axes):
        ax.xaxis.label.set_weight("normal")
        ax.yaxis.label.set_weight("normal")
    fig.legend(handles=[
        Line2D([], [], color=INK, label="FixG"),
        Line2D([], [], color=HERO, label="Online"),
        Line2D([], [], color=MUTED, marker="o", mfc="white", label="RMSE$_z$"),
        Line2D([], [], color=MUTED, marker="D", ls="--", mfc="white", label="ATE")],
        frameon=False, fontsize=6.7, loc="center", bbox_to_anchor=(.57, .52),
        ncol=4, columnspacing=.8, handlelength=1.3)
    fig.subplots_adjust(left=0.18, right=0.985, bottom=0.12, top=0.94)
    save(fig, "fig_direction")


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("fig_teaser", "all"):
        fig_teaser_rebuilt()
    if which in ("fig_design", "all"):
        fig_design_rebuilt()
    if which in ("fig_factorial", "all"):
        fig_factorial_rebuilt()
    if which == "fig_stress":
        fig_stress()
    if which in ("fig_boundary", "all"):
        fig_boundary_rebuilt()
    if which in ("fig_imuweight", "all"):
        fig_imuweight()
    if which in ("fig_direction", "all"):
        fig_direction_rebuilt()


if __name__ == "__main__":
    main()
