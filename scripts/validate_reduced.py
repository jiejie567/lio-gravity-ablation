#!/usr/bin/env python3
"""降维变体的正确性验证 —— 批量跑之前必须通过。

三个降维二进制各自把一部分状态移出状态向量,它们的行为必须与对应的
dx 清零策略一致(数值可以有小差异,那正是要测的量),但**结构性质**必须精确:

  变体      维度  重力      ba        对应策略
  main      23   在线估计  在线估计   A
  redg      21   常量      在线估计   B(只冻重力)
  redb      20   在线估计  常量       D(只冻 ba)
  red       18   常量      常量       C(两者都冻)

检查项(任一失败即不得开跑批次):
  1. 帧数与基线一致            —— 不一致说明处理的数据量不同,无法比较
  2. 轨迹弧长与 GT 同量级       —— 偏离说明估计已经跑飞
  3. 应为常量的状态确实恒定     —— 变动说明该状态没被真正移除
  4. 应在线的状态确实在变       —— 恒定说明误删了
  5. 重力模长 == 9.8090        —— 与 MTK::S2<double,98090,10000,1> 一致,
                                 否则引入与本实验无关的系统偏差(踩过)
  6. 重力方向与基线一致(<0.1°) —— 初始化路径必须等价

用法: validate_reduced.py <序列名> [--gt-len 米]
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
G_S2 = 98090.0 / 10000.0

# 变体 -> (运行名, 重力应恒定, ba 应恒定)
VARIANTS = {
    "A":     ("A",     False, False),
    "RED21": ("RED21", True,  False),
    "RED20": ("RED20", False, True),
    "RED18": ("RED18", True,  True),
}


def load(seq, run):
    """仍在写入的运行(2 分钟内有更新)不参与检查 —— 否则会把跑到一半的
    运行误报成帧数不足(与 collect_metrics.py 同一套保护)。"""
    import time
    import pandas as pd
    f = ROOT / "results" / seq / run / "state_log.csv"
    if not f.exists():
        return None
    if time.time() - f.stat().st_mtime < 120:
        return None
    return pd.read_csv(f).dropna()


def check(seq, gt_len=None, suffix=""):
    import numpy as np
    base = load(seq, "A" + suffix)
    if base is None:
        print(f"[跳过] {seq}: 无基线 A{suffix}")
        return True
    nb = len(base)
    ok_all = True
    for name, (run, grav_const, ba_const) in VARIANTS.items():
        d = load(seq, run + suffix)
        if d is None:
            continue
        issues = []
        p = d[["px", "py", "pz"]].values
        g = d[["gx", "gy", "gz"]].values
        ba = d[["bax", "bay", "baz"]].values
        bg = d[["bgx", "bgy", "bgz"]].values
        arc = float(np.linalg.norm(np.diff(p, axis=0), axis=1).sum())

        if len(d) != nb:
            issues.append(f"帧数 {len(d)} vs 基线 {nb}")
        if gt_len and not (0.6 <= arc / gt_len <= 1.6):
            issues.append(f"弧长 {arc:.0f} m vs GT {gt_len:.0f} m")

        gv = float(np.abs(g - g[0]).max())
        if grav_const and gv > 1e-12:
            issues.append(f"重力应恒定但变动 {gv:.1e}")
        if not grav_const and gv < 1e-12:
            issues.append("重力应在线估计但恒定")

        bav = float(np.abs(ba - ba[0]).max())
        if ba_const and bav > 1e-12:
            issues.append(f"ba 应恒定但变动 {bav:.1e}")
        if not ba_const and bav < 1e-12:
            issues.append("ba 应在线估计但恒定")

        if float(np.abs(bg - bg[0]).max()) < 1e-12:
            issues.append("bg 应始终在线估计但恒定")

        gn = float(np.linalg.norm(g[0]))
        if abs(gn - G_S2) > 1e-3:
            issues.append(f"重力模长 {gn:.4f} != {G_S2:.4f}")

        g0, gb = g[0] / gn, base[["gx", "gy", "gz"]].values[0]
        ang = np.degrees(np.arccos(np.clip(g0 @ (gb / np.linalg.norm(gb)), -1, 1)))
        if ang > 0.1:
            issues.append(f"重力方向与基线差 {ang:.2f}°")

        mark = "✓ 通过" if not issues else "✗ " + "; ".join(issues)
        label = name + suffix
        print(f"  {seq:22} {label:10} 帧{len(d):5d} 弧长{arc:7.0f}m  {mark}")
        ok_all &= not issues
    return ok_all


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("sequences", nargs="*")
    ap.add_argument("--gt-len", type=float, default=None)
    ap.add_argument("--suffix", default="",
                    help="验证重复运行后缀，例如 _r1 或 _r2")
    args = ap.parse_args()
    seqs = args.sequences
    summary = json.loads((ROOT / "report" / "summary.json").read_text())["sequences"]
    if not seqs:
        seqs = list(summary)
        print("降维变体验证(全序列)\n")
        ok = True
        for s in seqs:
            ok &= check(s, summary[s].get("gt", {}).get("path_len_m"), args.suffix)
        sys.exit(0 if ok else 1)
    print("降维变体验证\n")
    ok = True
    for s in seqs:
        gt_len = args.gt_len
        if gt_len is None:
            gt_len = summary.get(s, {}).get("gt", {}).get("path_len_m")
        ok &= check(s, gt_len, args.suffix)
    sys.exit(0 if ok else 1)
