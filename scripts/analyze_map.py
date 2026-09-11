#!/usr/bin/env python3
"""地图竖直一致性分析(容器内运行,不依赖 open3d)。

用法:
  analyze_map.py --seq-dir /work/results/<seq> --runs A B [--ground-band 0.3]

对每个 run 的 map.pcd:
  - 取 z 低位百分位附近 (ground-band 米内) 的点作为地面候选
  - RANSAC 拟合平面 → 地面厚度 (内点 RMS 距离) + 平面法向相对竖直的倾角
  - 输出侧视图 (x-z) 散点对比
结果并入 <seq-dir>/analysis/map_metrics.json 与 plots/side_view.png

注: 地面提取假设场景存在近水平的主地面(室内/平地),复杂地形需按数据集调整。
"""
import argparse, json, os, re, sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

RUN_COLORS = {"A": "tab:blue", "B": "tab:red", "C": "tab:green", "D": "tab:orange"}


def load_pcd_xyz(path):
    """解析 PCL 的 ascii/binary PCD,返回 Nx3 xyz。"""
    with open(path, "rb") as f:
        header = {}
        while True:
            line = f.readline().decode("ascii", errors="ignore").strip()
            key = line.split(" ")[0].upper() if line else ""
            if key:
                header[key] = line.split(" ")[1:]
            if key == "DATA":
                data_mode = header["DATA"][0]
                break
        fields = header["FIELDS"]
        sizes = [int(x) for x in header["SIZE"]]
        counts = [int(x) for x in header.get("COUNT", ["1"] * len(fields))]
        types = header["TYPE"]
        n = int(header["POINTS"][0])
        if data_mode == "ascii":
            a = np.loadtxt(f)
            idx = [fields.index(c) for c in ("x", "y", "z")]
            return a[:, idx]
        if data_mode != "binary":
            sys.exit(f"不支持的 PCD DATA 模式: {data_mode}")
        np_types = {("F", 4): "f4", ("F", 8): "f8", ("U", 1): "u1",
                    ("U", 2): "u2", ("U", 4): "u4", ("I", 1): "i1",
                    ("I", 2): "i2", ("I", 4): "i4"}
        dt = []
        for name, t, s, c in zip(fields, types, sizes, counts):
            base = np_types[(t, s)]
            dt.append((name, base, (c,)) if c > 1 else (name, base))
        dtype = np.dtype(dt)
        stride = max(1, n // 2_000_000)
        # 分块流式读取 + 块内抽样: GB 级 PCD 下内存恒定(容器 cgroup 连页缓存一起限)
        recs_per_chunk = (32 * 1024 * 1024) // dtype.itemsize
        chunks = []
        remaining = n
        while remaining > 0:
            k = min(recs_per_chunk, remaining)
            buf = f.read(k * dtype.itemsize)
            if len(buf) < dtype.itemsize:
                break
            arr = np.frombuffer(buf, dtype=dtype, count=len(buf) // dtype.itemsize)
            chunks.append(np.stack([arr["x"][::stride], arr["y"][::stride],
                                    arr["z"][::stride]], axis=1).astype(np.float64))
            remaining -= k
    return np.concatenate(chunks, axis=0)


def ransac_plane(pts, n_iter=300, thresh=0.05, seed=0):
    """返回 (normal, d, inlier_mask): n·p + d = 0"""
    rng = np.random.default_rng(seed)
    best = (None, None, np.zeros(len(pts), bool))
    for _ in range(n_iter):
        i = rng.choice(len(pts), 3, replace=False)
        p0, p1, p2 = pts[i]
        n = np.cross(p1 - p0, p2 - p0)
        nn = np.linalg.norm(n)
        if nn < 1e-9:
            continue
        n = n / nn
        d = -n @ p0
        inl = np.abs(pts @ n + d) < thresh
        if inl.sum() > best[2].sum():
            best = (n, d, inl)
    n, d, inl = best
    if n is None:
        sys.exit("RANSAC 平面拟合失败")
    # 用内点最小二乘精修
    c = pts[inl].mean(0)
    _, _, Vt = np.linalg.svd(pts[inl] - c, full_matrices=False)
    n = Vt[2]
    if n[2] < 0:
        n = -n
    d = -n @ c
    inl = np.abs(pts @ n + d) < thresh
    return n, d, inl


def main(args):
    seq_dir = args.seq_dir.rstrip("/")
    out_dir = os.path.join(seq_dir, "analysis")
    plot_dir = os.path.join(out_dir, "plots")
    os.makedirs(plot_dir, exist_ok=True)
    result = {}
    fig, axes = plt.subplots(len(args.runs), 1, figsize=(10, 3.2 * len(args.runs)),
                             sharex=True, sharey=True, squeeze=False)
    for k, r in enumerate(args.runs):
        pcd = os.path.join(seq_dir, r, "map.pcd")
        if not os.path.exists(pcd):
            print(f"跳过 {r}: 无 map.pcd")
            continue
        xyz = load_pcd_xyz(pcd)
        if len(xyz) > 2_000_000:
            xyz = xyz[np.random.default_rng(0).choice(len(xyz), 2_000_000, replace=False)]
        z1 = np.percentile(xyz[:, 2], 1)
        cand = xyz[(xyz[:, 2] > z1 - 0.1) & (xyz[:, 2] < z1 + args.ground_band)]
        if len(cand) < 500:
            print(f"跳过 {r}: 地面候选点太少 ({len(cand)})")
            continue
        if len(cand) > 200_000:
            cand = cand[np.random.default_rng(0).choice(len(cand), 200_000, replace=False)]
        n, d, inl = ransac_plane(cand)
        dist = cand[inl] @ n + d
        tilt = np.degrees(np.arccos(np.clip(abs(n[2]), 0, 1)))
        result[r] = {
            "points_total": int(len(xyz)),
            "ground_inliers": int(inl.sum()),
            "ground_rms_thickness_m": float(np.sqrt(np.mean(dist ** 2))),
            "ground_tilt_deg": float(tilt),
        }
        ax = axes[k][0]
        sub = xyz[np.random.default_rng(1).choice(len(xyz), min(len(xyz), 150_000), replace=False)]
        ax.scatter(sub[:, 0], sub[:, 2], s=0.05, c=RUN_COLORS.get(r), alpha=0.35, linewidths=0)
        ax.set_ylabel("z [m]")
        ax.set_title(f"method {r} — ground RMS {result[r]['ground_rms_thickness_m']*100:.1f} cm, "
                     f"tilt {tilt:.2f} deg")
        ax.grid(True, alpha=0.3)
    axes[-1][0].set_xlabel("x [m]")
    fig.suptitle(f"{os.path.basename(seq_dir)}: map side view (x-z)")
    fig.tight_layout()
    fig.savefig(f"{plot_dir}/side_view.png", dpi=150)
    with open(os.path.join(out_dir, "map_metrics.json"), "w") as f:
        json.dump(result, f, indent=2)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seq-dir", required=True)
    ap.add_argument("--runs", nargs="+", required=True)
    ap.add_argument("--ground-band", type=float, default=0.3)
    main(ap.parse_args())
