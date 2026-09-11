#!/usr/bin/env python3
"""Frozen-gravity 实验轨迹分析(容器内运行)。

用法:
  analyze.py --seq-dir /work/results/<seq> --runs A B \
             [--gt /work/data/<seq>_gt.txt --gt-format tum] \
             [--align-sec 10] [--t-offset 0.0]

输入: <seq-dir>/<run>/state_log.csv
      列: t,px,py,pz,qx,qy,qz,qw,vx,vy,vz,bgx,bgy,bgz,bax,bay,baz,gx,gy,gz,n_feats
GT:   TUM 格式 (t x y z qx qy qz qw, 空格分隔, # 开头为注释)
输出: <seq-dir>/analysis/ 下 metrics.json、plots/*.png、section.md
"""
import argparse, json, os, sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.spatial.transform import Rotation, Slerp

RUN_COLORS = {"A": "tab:blue", "B": "tab:red", "C": "tab:green", "D": "tab:orange"}


def load_run(seq_dir, run):
    path = os.path.join(seq_dir, run, "state_log.csv")
    df = pd.read_csv(path).dropna()   # 最后一行可能因节点被 kill 而写了一半
    if len(df) < 10:
        sys.exit(f"{path} 行数太少 ({len(df)})")
    return df


def load_gt_tum(path):
    """TUM: t x y z qx qy qz qw;MCD pose_inW.csv: num,t,x,y,z,qx,qy,qz,qw(带表头)。
    按每行数值个数自动识别,非数值行(表头/注释)跳过。"""
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                v = [float(x) for x in line.replace(",", " ").split()]
            except ValueError:
                continue
            if len(v) >= 9:      # MCD: 去掉行号列
                rows.append(v[1:9])
            elif len(v) >= 8:    # TUM
                rows.append(v[:8])
    a = np.array(rows)
    a = a[np.argsort(a[:, 0])]
    q = a[:, 4:8]
    # 仅位置真值的两种占位形态: 全零四元数(M2DGR Leica)或恒定四元数(ENWIDE 恒等值)
    if np.median(np.linalg.norm(q, axis=1)) < 1e-6 or np.ptp(q, axis=0).max() < 1e-9:
        q = None
    return {"t": a[:, 0], "p": a[:, 1:4], "q": q}  # q = xyzw 或 None


def interp_gt(gt, t_query):
    """把 GT 插值到估计时间戳;返回掩码(落在GT时间范围内的查询点)。"""
    mask = (t_query >= gt["t"][0]) & (t_query <= gt["t"][-1])
    tq = t_query[mask]
    p = np.stack([np.interp(tq, gt["t"], gt["p"][:, i]) for i in range(3)], axis=1)
    rot = Slerp(gt["t"], Rotation.from_quat(gt["q"]))(tq) if gt["q"] is not None else None
    return mask, p, rot


def umeyama_rigid(src, dst):
    """刚体对齐 (无尺度): dst ≈ R @ src + t"""
    mu_s, mu_d = src.mean(0), dst.mean(0)
    S, D = src - mu_s, dst - mu_d
    U, _, Vt = np.linalg.svd(D.T @ S)
    sgn = np.sign(np.linalg.det(U @ Vt))
    C = np.diag([1.0, 1.0, sgn])
    R = U @ C @ Vt
    t = mu_d - R @ mu_s
    return R, t


def grav_angle_deg(df):
    g = df[["gx", "gy", "gz"]].to_numpy()
    g0 = g[0] / np.linalg.norm(g[0])
    gn = g / np.linalg.norm(g, axis=1, keepdims=True)
    return np.degrees(np.arccos(np.clip(gn @ g0, -1.0, 1.0)))


def dist_to_past(t, p, lag_s=30.0):
    """每个位姿与 lag_s 秒之前轨迹的最近距离(隐式回环风险度)。"""
    step = max(1, len(t) // max(1, int((t[-1] - t[0]) * 2)))
    ti, pi = t[::step], p[::step]
    d = np.full(len(ti), np.inf)
    for i in range(len(ti)):
        past = pi[ti < ti[i] - lag_s]
        if len(past):
            d[i] = np.min(np.linalg.norm(past - pi[i], axis=1))
    return np.interp(t, ti, d)


def windowed_z_drift(t, p_al, p_gt, win_m=100.0, open_min_dist=0.0):
    """分窗开环 z 漂移率: 沿轨迹每前进 win_m 米取一段,取段末 |z 误差增量| / 段长。
    open_min_dist>0 时,只统计整窗都离既往轨迹足够远(真开环)的窗口。"""
    ds = np.linalg.norm(np.diff(p_gt, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(ds)])   # GT 弧长
    d_past = dist_to_past(t, p_gt) if open_min_dist > 0 else None
    rates, centers = [], []
    s0 = 0.0
    i0 = 0
    for i in range(len(s)):
        if s[i] - s0 >= win_m:
            if d_past is None or np.min(d_past[i0:i + 1]) >= open_min_dist:
                ez = (p_al[i, 2] - p_gt[i, 2]) - (p_al[i0, 2] - p_gt[i0, 2])
                rates.append(abs(ez) / (s[i] - s0) * 100.0)   # % of distance
                centers.append(0.5 * (t[i0] + t[i]))
            s0 = s[i]; i0 = i
    return np.array(rates), np.array(centers)


def analyze(args):
    seq_dir = args.seq_dir.rstrip("/")
    seq = os.path.basename(seq_dir)
    out_dir = os.path.join(seq_dir, "analysis")
    plot_dir = os.path.join(out_dir, "plots")
    os.makedirs(plot_dir, exist_ok=True)

    runs = {r: load_run(seq_dir, r) for r in args.runs}
    gt = load_gt_tum(args.gt) if args.gt else None
    if gt is not None:
        gt["t"] = gt["t"] + args.t_offset

    metrics = {"sequence": seq, "runs": {}}
    aligned = {}   # run -> dict(t, p_est_aligned, p_gt, rot_est_aligned, rot_gt)

    for r, df in runs.items():
        m = {"frames": int(len(df)),
             "duration_s": float(df.t.iloc[-1] - df.t.iloc[0]),
             "grav_angle_final_deg": float(grav_angle_deg(df)[-1]),
             "grav_angle_max_deg": float(grav_angle_deg(df).max())}
        if gt is not None:
            t = df.t.to_numpy()
            mask, p_gt, rot_gt = interp_gt(gt, t)
            p_est = df[["px", "py", "pz"]].to_numpy()[mask]
            rot_est = Rotation.from_quat(df[["qx", "qy", "qz", "qw"]].to_numpy()[mask])
            if args.est2body is not None:
                # est(如 os_imu) -> body(GT 帧) 的常量外参: T_W_body = T_W_est * T_est_body
                e = np.array(args.est2body)
                t_eb, R_eb = e[:3], e[3:].reshape(3, 3)
                p_est = p_est + rot_est.apply(t_eb)
                rot_est = rot_est * Rotation.from_matrix(R_eb)
            t = t[mask]
            # 对齐窗: 时间够长且走过足够弧长(起步静止的序列光按时间取窗会几何退化)
            s_gt = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(p_gt, axis=0), axis=1))])
            n_align = max(10, np.searchsorted(t, t[0] + args.align_sec),
                          int(np.searchsorted(s_gt, args.align_m)))
            n_align = min(n_align, len(t) - 1)
            R_A, t_A = umeyama_rigid(p_est[:n_align], p_gt[:n_align])
            p_al = p_est @ R_A.T + t_A
            rot_al = Rotation.from_matrix(R_A) * rot_est
            e_z = p_al[:, 2] - p_gt[:, 2]
            e3 = np.linalg.norm(p_al - p_gt, axis=1)
            tail = t >= t[-1] - 2.0
            # 姿态误差: R_err = R_gt^-1 * R_est_aligned, ZYX 分解取 roll/pitch(仅位置真值时跳过)
            eul = (rot_gt.inv() * rot_al).as_euler("ZYX", degrees=True) if rot_gt is not None else None
            zr, _ = windowed_z_drift(t, p_al, p_gt, win_m=args.drift_win_m,
                                     open_min_dist=args.open_loop_min_dist)
            m.update({
                "align_sec": args.align_sec,
                "rmse_z_m": float(np.sqrt(np.mean(e_z ** 2))),
                "max_abs_z_err_m": float(np.abs(e_z).max()),
                "final_z_drift_m": float(e_z[tail].mean()),
                "ate_rmse_m": float(np.sqrt(np.mean(e3 ** 2))),
                "rmse_roll_deg": float(np.sqrt(np.mean(eul[:, 2] ** 2))) if eul is not None else None,
                "rmse_pitch_deg": float(np.sqrt(np.mean(eul[:, 1] ** 2))) if eul is not None else None,
                # 分窗开环 z 漂移率: 对局部地图的隐式回环免疫
                "z_drift_pct_median": float(np.median(zr)) if len(zr) else None,
                "z_drift_pct_p90": float(np.percentile(zr, 90)) if len(zr) else None,
                "z_drift_windows": int(len(zr)),
            })
            aligned[r] = dict(t=t, p_al=p_al, p_gt=p_gt, e_z=e_z, eul=eul)
        metrics["runs"][r] = m

    t0 = min(df.t.iloc[0] for df in runs.values())

    def ax_style(ax, xlabel, ylabel, title):
        ax.set_xlabel(xlabel); ax.set_ylabel(ylabel); ax.set_title(title)
        ax.grid(True, alpha=0.3); ax.legend()

    # 1. z 轨迹
    fig, ax = plt.subplots(figsize=(9, 4))
    if gt is not None and aligned:
        r0 = args.runs[0]
        ax.plot(aligned[r0]["t"] - t0, aligned[r0]["p_gt"][:, 2], "k--", lw=1.2, label="GT")
        for r in args.runs:
            ax.plot(aligned[r]["t"] - t0, aligned[r]["p_al"][:, 2],
                    color=RUN_COLORS.get(r), lw=1.0, label=f"method {r}")
    else:
        for r, df in runs.items():
            ax.plot((df.t - t0).to_numpy(), df.pz.to_numpy(),
                    color=RUN_COLORS.get(r), lw=1.0, label=f"method {r}")
    ax_style(ax, "time [s]", "z [m]", f"{seq}: z trajectory")
    fig.tight_layout(); fig.savefig(f"{plot_dir}/z_traj.png", dpi=150); plt.close(fig)

    # 2. z 误差 (需 GT)
    if gt is not None and aligned:
        fig, ax = plt.subplots(figsize=(9, 4))
        for r in args.runs:
            ax.plot(aligned[r]["t"] - t0, aligned[r]["e_z"],
                    color=RUN_COLORS.get(r), lw=1.0, label=f"method {r}")
        ax.axhline(0, color="k", lw=0.5)
        ax_style(ax, "time [s]", "e_z [m]", f"{seq}: z error (est - GT)")
        fig.tight_layout(); fig.savefig(f"{plot_dir}/z_err.png", dpi=150); plt.close(fig)

    # 3. gravity 方向夹角
    fig, ax = plt.subplots(figsize=(9, 4))
    for r, df in runs.items():
        ax.plot((df.t - t0).to_numpy(), grav_angle_deg(df),
                color=RUN_COLORS.get(r), lw=1.0, label=f"method {r}")
    ax_style(ax, "time [s]", "angle(g_t, g_0) [deg]", f"{seq}: gravity direction change")
    fig.tight_layout(); fig.savefig(f"{plot_dir}/grav_angle.png", dpi=150); plt.close(fig)

    # 4. roll/pitch 误差 (需带姿态的 GT)
    if gt is not None and aligned and next(iter(aligned.values()))["eul"] is not None:
        fig, axes = plt.subplots(2, 1, figsize=(9, 6), sharex=True)
        for r in args.runs:
            axes[0].plot(aligned[r]["t"] - t0, aligned[r]["eul"][:, 2],
                         color=RUN_COLORS.get(r), lw=1.0, label=f"method {r}")
            axes[1].plot(aligned[r]["t"] - t0, aligned[r]["eul"][:, 1],
                         color=RUN_COLORS.get(r), lw=1.0, label=f"method {r}")
        axes[0].set_ylabel("roll err [deg]"); axes[1].set_ylabel("pitch err [deg]")
        for a in axes:
            a.grid(True, alpha=0.3); a.legend(); a.axhline(0, color="k", lw=0.5)
        axes[1].set_xlabel("time [s]")
        axes[0].set_title(f"{seq}: attitude error vs GT")
        fig.tight_layout(); fig.savefig(f"{plot_dir}/rp_err.png", dpi=150); plt.close(fig)

    # 5. xy 俯视轨迹
    fig, ax = plt.subplots(figsize=(6, 6))
    if gt is not None and aligned:
        r0 = args.runs[0]
        ax.plot(aligned[r0]["p_gt"][:, 0], aligned[r0]["p_gt"][:, 1], "k--", lw=1.2, label="GT")
        for r in args.runs:
            ax.plot(aligned[r]["p_al"][:, 0], aligned[r]["p_al"][:, 1],
                    color=RUN_COLORS.get(r), lw=1.0, label=f"method {r}")
    else:
        for r, df in runs.items():
            ax.plot(df.px.to_numpy(), df.py.to_numpy(),
                    color=RUN_COLORS.get(r), lw=1.0, label=f"method {r}")
    ax.set_aspect("equal")
    ax_style(ax, "x [m]", "y [m]", f"{seq}: top view")
    fig.tight_layout(); fig.savefig(f"{plot_dir}/xy_traj.png", dpi=150); plt.close(fig)

    with open(os.path.join(out_dir, "metrics.json"), "w") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)

    # section.md
    lines = [f"## 序列 {seq}", ""]
    cols = ["rmse_z_m", "max_abs_z_err_m", "final_z_drift_m", "ate_rmse_m",
            "rmse_roll_deg", "rmse_pitch_deg", "grav_angle_final_deg"]
    have = [c for c in cols if any(c in metrics["runs"][r] for r in args.runs)]
    lines.append("| method | " + " | ".join(have) + " |")
    lines.append("|" + "---|" * (len(have) + 1))
    fmt = lambda v: "—" if v is None else f"{v:.4f}"
    for r in args.runs:
        vals = [fmt(metrics["runs"][r].get(c)) for c in have]
        lines.append(f"| {r} | " + " | ".join(vals) + " |")
    lines += ["", f"![z traj](plots/z_traj.png)"]
    if gt is not None:
        lines += [f"![z err](plots/z_err.png)", f"![rp err](plots/rp_err.png)"]
    lines += [f"![gravity angle](plots/grav_angle.png)", f"![top view](plots/xy_traj.png)", ""]
    if gt is None:
        lines.append("> 注: 本序列无 ground truth,仅展示各方法自身输出的对比。")
    with open(os.path.join(out_dir, "section.md"), "w") as f:
        f.write("\n".join(lines))
    print(json.dumps(metrics, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seq-dir", required=True)
    ap.add_argument("--runs", nargs="+", required=True)
    ap.add_argument("--gt", default=None)
    ap.add_argument("--gt-format", default="tum", choices=["tum"])
    ap.add_argument("--align-sec", type=float, default=10.0)
    ap.add_argument("--align-m", type=float, default=30.0,
                    help="对齐窗最少覆盖的 GT 弧长(米),防起步静止的几何退化")
    ap.add_argument("--t-offset", type=float, default=0.0)
    ap.add_argument("--est2body", type=float, nargs=12, default=None,
                    metavar="V", help="est帧->body帧常量外参: tx ty tz + R(行主序9个)")
    ap.add_argument("--drift-win-m", type=float, default=100.0,
                    help="分窗漂移率的窗口长度(米)")
    ap.add_argument("--open-loop-min-dist", type=float, default=0.0,
                    help=">0 时只统计离既往轨迹至少此距离(米)的真开环窗口")
    analyze(ap.parse_args())
