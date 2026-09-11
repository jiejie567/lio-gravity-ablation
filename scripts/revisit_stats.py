#!/usr/bin/env python3
"""从 GT 统计轨迹自交/折返几何: 每个位姿与 30s 前轨迹的最近距离。
决定 det_range/cube_len 需要多小才能避免隐式回环。"""
import sys
import numpy as np

for path in sys.argv[1:]:
    rows = []
    for line in open(path):
        try:
            v = [float(x) for x in line.replace(",", " ").split()]
        except ValueError:
            continue
        if len(v) >= 9:
            rows.append(v[1:5])
    a = np.array(rows)          # t x y z
    t, p = a[:, 0], a[:, 1:4]
    ds = np.linalg.norm(np.diff(p, axis=0), axis=1)
    total = ds.sum()
    # 下采样到 ~2Hz 降低计算量
    step = max(1, len(t) // int((t[-1] - t[0]) * 2))
    ti, pi = t[::step], p[::step]
    mind = []
    for i in range(len(ti)):
        past = pi[ti < ti[i] - 30.0]
        if len(past) == 0:
            continue
        mind.append(np.min(np.linalg.norm(past - pi[i], axis=1)))
    mind = np.array(mind)
    frac_close = lambda r: float((mind < r).mean()) * 100
    print(f"{path.split('/')[-3]}: 路径 {total:.0f} m, 时长 {t[-1]-t[0]:.0f} s")
    print(f"  与30s前轨迹距离 < 50m 的时段占比: {frac_close(50):.0f}%")
    print(f"  < 80m: {frac_close(80):.0f}%   < 150m: {frac_close(150):.0f}%   最小值: {mind.min():.1f} m")
