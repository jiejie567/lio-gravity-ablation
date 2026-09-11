#!/usr/bin/env python3
"""统一重算所有序列指标 -> report/summary.json(论文数字唯一来源)。

用法: .venv/bin/python scripts/collect_metrics.py [--only seq1 seq2] [--skip-analyze]
每序列用同一版本 analyze.py + 固定协议参数(50m 窗 / ≥80m 复访掩膜)跑一遍,
再把各 results/<seq>/analysis/metrics.json 合并;论文图表脚本只读 summary.json。
"""
import argparse, csv, json, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

E2B_ATV = ("0.054216 -0.001058 -0.028667 0.999935 0.003587 -0.010854 "
           "0.003478 -0.999943 -0.010092 -0.010890 0.010054 -0.999890").split()
E2B_HHS = ("0.042216 -0.019535 -0.026406 0.999914 -0.011356 -0.006635 "
           "-0.011166 -0.999545 0.028009 -0.006950 -0.027932 -0.999586").split()

def mcd(base, e2b, *, clip_gt_to_est=False):
    return {"gt": f"data/mcd/{base}/gt/pose_inW.csv", "est2body": e2b,
            "clip_gt_to_est": clip_gt_to_est}

# 序列注册表:GT 路径 + est->body 外参(None = 恒等)。协议参数全局统一。
SEQS = {
    "ntu_day_01_os1":   mcd("ntu_day_01", E2B_ATV),
    "ntu_day_02_os1":   mcd("ntu_day_02", E2B_ATV),
    "ntu_day_10_os1":   mcd("ntu_day_10", E2B_ATV),
    "ntu_night_04_os1": mcd("ntu_night_04", E2B_ATV),
    "ntu_night_13_os1": mcd("ntu_night_13", E2B_ATV),
    "kth_day_10_os1":   mcd("kth_day_10", E2B_HHS),
    "kth_night_05_os1": mcd("kth_night_05", E2B_HHS),
    "tuhh_day_02_os1":  mcd("tuhh_day_02", E2B_HHS),
    "tuhh_day_04_os1":  mcd("tuhh_day_04", E2B_HHS),
    "tuhh_night_09_os1": mcd("tuhh_night_09", E2B_HHS),
    "IndoorOffice1":    {"gt": "data/tiers/IndoorOffice1/gt.txt", "est2body": None},
    "OutdoorRoad_cut1": {"gt": "data/tiers/OutdoorRoad_cut1/gt.txt", "est2body": None},
    "hall_05_run":      {"gt": "data/m2dgr/hall_05/gt/gt.txt", "est2body": None},
    # ntu_day_10 受控退化变体(degrade_bag.py 产物,GT 与母序列相同)
    "ntu_day_10_range20":  mcd("ntu_day_10", E2B_ATV),
    "ntu_day_10_range10":  mcd("ntu_day_10", E2B_ATV),
    "ntu_day_10_fov60":    mcd("ntu_day_10", E2B_ATV),
    "ntu_day_10_fov30":    mcd("ntu_day_10", E2B_ATV),
    "ntu_day_10_drop1x20": mcd("ntu_day_10", E2B_ATV),
    "ntu_day_10_drop2x20": mcd("ntu_day_10", E2B_ATV),
    "ntu_day_10_drop3x20": mcd("ntu_day_10", E2B_ATV),
    "ntu_day_10_drop3x20_s12": mcd("ntu_day_10", E2B_ATV),
    "ntu_day_10_drop3x20_s22": mcd("ntu_day_10", E2B_ATV),
    "ntu_day_10_drop5x20": mcd("ntu_day_10", E2B_ATV),
    "ntu_day_10_drop10x20": mcd("ntu_day_10", E2B_ATV),
    "ntu_day_10_fastinit_s130p072": mcd(
        "ntu_day_10", E2B_ATV, clip_gt_to_est=True),
    "ntu_day_10_fastinit_s189p471": mcd(
        "ntu_day_10", E2B_ATV, clip_gt_to_est=True),
    "tuhh_day_04_drop2x20": mcd("tuhh_day_04", E2B_HHS),
    "tuhh_day_04_drop3x20": mcd("tuhh_day_04", E2B_HHS),
    "tuhh_day_04_drop5x20": mcd("tuhh_day_04", E2B_HHS),
    "tuhh_day_04_fastinit_s70p572": mcd(
        "tuhh_day_04", E2B_HHS, clip_gt_to_est=True),
    "tuhh_day_04_fastinit_s114p279": mcd(
        "tuhh_day_04", E2B_HHS, clip_gt_to_est=True),
    "tuhh_day_04_drop5x20_s12": mcd("tuhh_day_04", E2B_HHS),
    "tuhh_day_04_drop5x20_s22": mcd("tuhh_day_04", E2B_HHS),
}

PROTO = ["--align-sec", "10", "--align-m", "30",
         "--drift-win-m", "50", "--open-loop-min-dist", "80"]

def runs_of(seq_dir: Path):
    out = []
    for d in sorted(seq_dir.iterdir()):
        if not d.is_dir() or d.name == "analysis":
            continue
        if d.name.endswith("_truncated") or d.name.endswith("_sleepdamaged"):
            continue
        log = d / "state_log.csv"
        if log.exists():
            # 仍在写入的运行(2 分钟内有更新)不收,防半截日志混进论文数字
            if time.time() - log.stat().st_mtime < 120:
                print(f"[skip] {seq_dir.name}/{d.name}: state_log 仍在写入")
                continue
            out.append(d.name)
    return out


def run_meta(path: Path):
    """读取 run_meta.txt；字段原样保留，便于追溯实际启动对象。"""
    out = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        out[key.strip()] = value.strip()
    return out


def baseline_log(seq_dir: Path) -> Path:
    """Return the available online-state control used by the data-quality gates."""
    for name in ("A", "A_warm21", "A_warm21_r1"):
        candidate = seq_dir / name / "state_log.csv"
        if candidate.exists():
            return candidate
    return seq_dir / "A" / "state_log.csv"

def estimate_time_range(seq_dir):
    """Return the timestamp support of the online baseline state log."""
    log = baseline_log(seq_dir)
    if not log.exists():
        return None
    with log.open(newline="") as stream:
        rows = csv.DictReader(stream)
        times = []
        for row in rows:
            try:
                times.append(float(row["t"]))
            except (KeyError, TypeError, ValueError):
                continue
    return (times[0], times[-1]) if len(times) >= 2 else None


def gt_extent(gt_path, time_range=None):
    """真值轨迹的弧长与时长(注意 MCD pose_inW.csv 首列是行号 num,时间在第 2 列)"""
    import numpy as np
    rows = []
    for line in Path(gt_path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            v = [float(x) for x in line.replace(",", " ").split()]
        except ValueError:
            continue
        if len(v) >= 9:
            rows.append(v[1:5])      # MCD: 去行号 -> t x y z
        elif len(v) >= 8:
            rows.append(v[:4])       # TUM
    a = np.array(rows)
    a = a[np.argsort(a[:, 0])]
    if time_range is not None:
        lo = max(float(time_range[0]), float(a[0, 0]))
        hi = min(float(time_range[1]), float(a[-1, 0]))
        if hi <= lo:
            raise ValueError(f"GT 与估计时间不重叠: {gt_path}")
        inner = a[(a[:, 0] > lo) & (a[:, 0] < hi)]
        boundary = []
        for timestamp in (lo, hi):
            xyz = [np.interp(timestamp, a[:, 0], a[:, axis])
                   for axis in range(1, 4)]
            boundary.append([timestamp, *xyz])
        a = np.vstack((boundary[0], inner, boundary[1]))
    return {"path_len_m": float(np.linalg.norm(np.diff(a[:, 1:4], axis=0), axis=1).sum()),
            "duration_s": float(a[-1, 0] - a[0, 0]),
            "extent_scope": "estimate_timestamp_overlap" if time_range else "full_gt"}


def grav_selffreeze(seq_dir):
    """基线 A 的重力方向漂移率: 首 1/8 段 vs 末 1/8 段(度/分)。
    grav 无过程噪声 → 增益单调衰减 → 在线估计会自行冻结,这是该论断的实测依据。"""
    import numpy as np
    log = baseline_log(seq_dir)
    if not log.exists():
        return None
    try:
        import pandas as pd
        d = pd.read_csv(log).dropna()
    except Exception:
        return None
    if len(d) < 100 or not {"gx", "gy", "gz", "t"} <= set(d.columns):
        return None
    t = d["t"].values - d["t"].values[0]
    g = d[["gx", "gy", "gz"]].values
    gn = g / np.linalg.norm(g, axis=1, keepdims=True)
    n, k = len(t), len(t) // 8

    def rate(s, e):
        ang = np.degrees(np.arccos(np.clip(float(gn[s] @ gn[e]), -1, 1)))
        dt = (t[e] - t[s]) / 60.0
        return float(ang / dt) if dt > 0 else None

    return {"first8_deg_per_min": rate(0, k), "last8_deg_per_min": rate(n - 1 - k, n - 1)}


def gt_sanity(seq_dir, gt_len, lo=0.6, hi=1.6):
    """在线基线的估计弧长与 GT 弧长之比落在 [lo,hi] 之外 → 判 GT 不可用"""
    import numpy as np
    log = baseline_log(seq_dir)
    if not log.exists() or not gt_len:
        return True, float("nan")
    rows = []
    with open(log) as f:
        next(f, None)
        for line in f:
            parts = line.split(",")
            if len(parts) >= 4:
                try:
                    rows.append([float(parts[1]), float(parts[2]), float(parts[3])])
                except ValueError:
                    continue
    if len(rows) < 2:
        return True, float("nan")
    p = np.array(rows)
    est = float(np.linalg.norm(np.diff(p, axis=0), axis=1).sum())
    ratio = est / gt_len
    return (lo <= ratio <= hi), ratio


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="+", default=None)
    ap.add_argument("--skip-analyze", action="store_true",
                    help="只合并既有 metrics.json,不重跑")
    args = ap.parse_args()

    out_path = ROOT / "report" / "summary.json"
    summary = {"protocol": {"align_sec": 10, "align_m": 30,
                            "drift_win_m": 50, "open_loop_min_dist_m": 80,
                            "analyzer": "scripts/analyze.py"},
               "sequences": {}}
    # --only 是"更新这几条",不是"只保留这几条": 先读入既有结果再覆盖,
    # 否则一次带 --only 的调用会把其余序列从 summary 里抹掉。
    if args.only and out_path.exists():
        try:
            summary["sequences"] = json.loads(out_path.read_text()).get("sequences", {})
        except Exception:
            pass
    failures = []
    for seq, cfg in SEQS.items():
        if args.only and seq not in args.only:
            continue
        seq_dir = ROOT / "results" / seq
        gt = ROOT / cfg["gt"]
        if not seq_dir.exists():
            continue
        if not gt.exists():
            failures.append(f"{seq}: GT 不存在 {cfg['gt']}")
            continue
        runs = runs_of(seq_dir)
        if not runs:
            continue
        if not args.skip_analyze:
            cmd = [PY, str(ROOT / "scripts/analyze.py"),
                   "--seq-dir", str(seq_dir), "--runs", *runs,
                   "--gt", str(gt), *PROTO]
            if cfg["est2body"]:
                cmd += ["--est2body", *cfg["est2body"]]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                failures.append(f"{seq}: analyze 失败\n{r.stderr[-500:]}")
                continue
        mfile = seq_dir / "analysis" / "metrics.json"
        if mfile.exists():
            entry = json.loads(mfile.read_text())
            time_range = (estimate_time_range(seq_dir)
                          if cfg.get("clip_gt_to_est") else None)
            entry["gt"] = gt_extent(gt, time_range)  # 真值弧长/时长,供表格与正文宏使用
            # GT 健全性闸门: 真值弧长与估计弧长必须同量级。TIERS OutdoorRoad 的
            # gt.txt 在 x/y 上是静止的(range<1mm),由此算出的 RMSE 全是对齐残差,
            # 曾一路混进表格与结论 —— 这里挡住,不让坏 GT 再进论文。
            a_run = None
            runs_d = entry.get("runs", {})
            if isinstance(runs_d, dict):
                a_run = (runs_d.get("A") or runs_d.get("A_warm21")
                         or runs_d.get("A_warm21_r1"))
            att = [a_run.get(k) for k in ("rmse_roll_deg", "rmse_pitch_deg")] if a_run else []
            att = [x for x in att if x is not None]
            # 姿态真值可能与估计不同帧(TIERS indoor 实测 roll RMSE 86.8°),单独闸门
            entry["gt"]["attitude_usable"] = bool(att) and max(att) < 20.0
            entry["grav_selffreeze"] = grav_selffreeze(seq_dir)
            # 记录每个 run 的源码与实际启动二进制指纹: commit 只表示源码状态，
            # 不能替代编译产物 SHA1。launch 也必须同行保存，避免记错二进制对象。
            rd = entry.get("runs", {})
            if isinstance(rd, dict):
                for name, rec in rd.items():
                    meta = run_meta(seq_dir / name / "run_meta.txt")
                    if meta.get("fastlio_commit"):
                        rec["commit"] = meta["fastlio_commit"][:7]
                    for source, dest in (("method", "method"),
                                         ("launch", "launch"),
                                         ("fastlio_binary_mtime", "binary_mtime"),
                                         ("fastlio_binary_sha1", "binary_sha1")):
                        if meta.get(source):
                            rec[dest] = meta[source]
                    log = seq_dir / name / "state_log.csv"
                    if log.exists():
                        with open(log) as fh:
                            rec["log_lines"] = sum(1 for _ in fh)
            ok, ratio = gt_sanity(seq_dir, entry["gt"]["path_len_m"])
            entry["gt"]["est_over_gt_ratio"] = ratio
            entry["gt"]["usable"] = ok
            rd2 = entry.get("runs", {})
            if isinstance(rd2, dict) and len(rd2) >= 3:
                import statistics
                counts = [r.get("log_lines") for r in rd2.values() if r.get("log_lines")]
                if counts:
                    med = statistics.median(counts)
                    # 容差为 0:同一序列的所有运行喂的是同一个 bag,帧数必须完全相同。
                    # 实测少 1 帧(强制终止时最后一行写到一半被 SIGKILL 截断)就足以
                    # 让 RMSE_z 变动 2.5% —— 比本文要测的效应还大,所以不留容差。
                    mode = statistics.mode(counts)
                    ref_z = rd2.get("A", {}).get("rmse_z_m")
                    for name, rec in rd2.items():
                        n = rec.get("log_lines")
                        if not n or n == mode:
                            continue
                        z = rec.get("rmse_z_m")
                        diverged = ref_z and z and z > max(5 * ref_z, ref_z + 10)
                        rec["frames_mismatch"] = n - mode
                        # 发散跑帧数本就会少,那是现象不是故障,仍参与统计
                        rec["usable"] = bool(diverged)
                        if not diverged:
                            failures.append(
                                f"{seq}/{name}: 处理了 {n} 帧(众数 {mode}, 中位 {med:.0f}),"
                                f"误差正常 → 判为帧数不一致,已排除")
            summary["sequences"][seq] = entry
            note = "" if ok else f"  ← GT 不可用(est/gt={ratio:.1f}),已标记排除"
            if not ok:
                failures.append(f"{seq}: GT 健全性未通过 (est/gt={ratio:.2f})")
            print(f"[ok] {seq}: {len(runs)} runs, GT {entry['gt']['path_len_m']:.0f} m{note}")

    out_path.write_text(json.dumps(summary, indent=1))
    print(f"\nsummary -> {out_path} ({len(summary['sequences'])} 序列)")
    for f in failures:
        print(f"[fail] {f}")
    return 1 if failures else 0

if __name__ == "__main__":
    sys.exit(main())
