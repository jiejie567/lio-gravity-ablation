#!/usr/bin/env python3
"""stdin 读 analyze.py 的 JSON,打印紧凑表格。"""
import json, sys

d = json.loads(sys.stdin.read())
print(f"== {d['sequence']}")
for r, m in d["runs"].items():
    zm = m.get("z_drift_pct_median")
    zs = "  None" if zm is None else f"{zm:6.3f}"
    print(f"  {r:>8} RMSE_z={m['rmse_z_m']:7.3f} ATE={m['ate_rmse_m']:7.3f} "
          f"漂移率={zs}% grav={m['grav_angle_final_deg']:6.3f}° 帧={m['frames']}")
