#!/usr/bin/env python3
"""姿态倾斜误差随时间的增长(地图渐进翘曲速率的轨迹侧度量)。
对每个 run: 与 GT 姿态比对,前 30s 常量对齐后,输出四分段的 roll/pitch 合成倾斜均值。"""
import csv, sys
import numpy as np
from scipy.spatial.transform import Rotation, Slerp

base = "/work"
seq, gt_path, runs = sys.argv[1], sys.argv[2], sys.argv[3:]

gt_rows = []
for line in open(gt_path):
    try:
        v = [float(x) for x in line.replace(",", " ").split()]
    except ValueError:
        continue
    if len(v) >= 9:
        gt_rows.append(v[1:9])
g = np.array(gt_rows); g = g[np.argsort(g[:, 0])]
gt_t, gt_q = g[:, 0], g[:, 4:8]
sl = Slerp(gt_t, Rotation.from_quat(gt_q))

for run in runs:
    rows = [r for r in list(csv.reader(open(f"{base}/results/{seq}/{run}/state_log.csv")))[1:] if len(r) >= 8]
    t = np.array([float(r[0]) for r in rows]) + 0.1
    q = np.array([[float(r[k]) for k in (4, 5, 6, 7)] for r in rows])
    m = (t >= gt_t[0]) & (t <= gt_t[-1]); t = t[m]; q = q[m]
    Rest = Rotation.from_quat(q); Rgt = sl(t)
    n0 = np.searchsorted(t, t[0] + 30)
    Rrel = (Rgt[:n0].inv() * Rest[:n0]).mean()
    Rerr = Rgt.inv() * Rest * Rrel.inv()
    eul = Rerr.as_euler("ZYX", degrees=True)
    tilt = np.sqrt(eul[:, 1] ** 2 + eul[:, 2] ** 2)
    T = t[-1] - t[0]
    qs = [float(np.mean(tilt[(t - t[0] >= T * a) & (t - t[0] < T * b)]))
          for a, b in [(0, .25), (.25, .5), (.5, .75), (.75, 1.001)]]
    print(f"{run:>3}: 四分段倾斜均值 = {[round(x,2) for x in qs]} °   末/首 = {qs[3]/max(qs[0],1e-6):.1f}x")
