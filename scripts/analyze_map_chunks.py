#!/usr/bin/env python3
"""实验D: 拼接地图的姿态-时间曲线(容器内运行)。
对每个 run 目录下按 interval 分块保存的 scans_*.pcd,逐块做地面 RANSAC,
输出"地面法向倾角 vs 块序号(时间)"曲线 + 汇总 json。
用法: analyze_map_chunks.py --seq-dir /work/results/<seq> --runs A_pcd B_pcd C_pcd D_pcd
"""
import argparse, glob, json, os, re, sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze_map import load_pcd_xyz, ransac_plane

RUN_COLORS = {"A": "tab:blue", "B": "tab:red", "C": "tab:green", "D": "tab:orange"}


def chunk_tilt(pcd_path, ground_band=0.3):
    xyz = load_pcd_xyz(pcd_path)
    if len(xyz) < 5000:
        return None
    z1 = np.percentile(xyz[:, 2], 2)
    cand = xyz[(xyz[:, 2] > z1 - 0.1) & (xyz[:, 2] < z1 + ground_band)]
    if len(cand) < 500:
        return None
    if len(cand) > 150_000:
        cand = cand[np.random.default_rng(0).choice(len(cand), 150_000, replace=False)]
    n, d, inl = ransac_plane(cand)
    return float(np.degrees(np.arccos(np.clip(abs(n[2]), 0, 1))))


def main(args):
    out_dir = os.path.join(args.seq_dir, "analysis")
    os.makedirs(os.path.join(out_dir, "plots"), exist_ok=True)
    result = {}
    fig, ax = plt.subplots(figsize=(8, 4))
    for run in args.runs:
        pcds = glob.glob(os.path.join(args.seq_dir, run, "pcd", "scans_*.pcd"))
        if not pcds:
            pcds = glob.glob(os.path.join(args.seq_dir, run, "scans_*.pcd"))
        pcds = sorted(pcds, key=lambda p: int(re.search(r"scans_(\d+)", p).group(1)))
        tilts = []
        for p in pcds:
            t = chunk_tilt(p, args.ground_band)
            tilts.append(t)
        result[run] = tilts
        xs = [i for i, t in enumerate(tilts) if t is not None]
        ys = [t for t in tilts if t is not None]
        key = run.split("_")[0]
        ax.plot(xs, ys, "o-", color=RUN_COLORS.get(key), label=f"method {key}")
        print(f"{run}: {len(pcds)} 块, 倾角序列 = {[None if t is None else round(t,3) for t in tilts]}")
    ax.set_xlabel("map chunk index (time-ordered)")
    ax.set_ylabel("ground-plane tilt vs frozen vertical [deg]")
    ax.set_title(f"{os.path.basename(args.seq_dir)}: stitched-map attitude over time")
    ax.grid(True, alpha=0.3); ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, "plots", "map_tilt_vs_time.png"), dpi=150)
    with open(os.path.join(out_dir, "map_chunks.json"), "w") as f:
        json.dump(result, f, indent=2)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seq-dir", required=True)
    ap.add_argument("--runs", nargs="+", required=True)
    ap.add_argument("--ground-band", type=float, default=0.3)
    main(ap.parse_args())
