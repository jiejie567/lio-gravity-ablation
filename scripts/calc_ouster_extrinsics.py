#!/usr/bin/env python3
"""从 MCD 标定文件计算 Ouster 内置 IMU 方案所需外参(容器内运行)。
输出: (1) FAST-LIO 用的 os_imu->os_sensor;(2) 评测用的 os_imu->body。"""
import numpy as np, yaml

for name in ["atv", "handheld"]:
    c = yaml.safe_load(open(f"/work/data/mcd/calib/{name}_calib_file"))["body"]
    T = {k: np.array(v["T"]) for k, v in c.items() if isinstance(v, dict) and "T" in v}
    bs, bi = T["os_sensor"], T["os_imu"]
    ii = np.linalg.inv(bi) @ bs      # os_imu -> os_sensor (FAST-LIO extrinsic 候选)
    ib = np.linalg.inv(bi)           # os_imu -> body (评测帧变换)
    print(f"== {name}")
    print("body->os_sensor T:", np.round(bs[:3, 3], 4).tolist())
    print("body->os_sensor R:", [np.round(r, 4).tolist() for r in bs[:3, :3]])
    print("body->os_imu    T:", np.round(bi[:3, 3], 4).tolist())
    print("os_imu->os_sensor T:", np.round(ii[:3, 3], 6).tolist())
    print("os_imu->os_sensor R:", [np.round(r, 6).tolist() for r in ii[:3, :3]])
    print("os_imu->body T:", np.round(ib[:3, 3], 6).tolist())
    print("os_imu->body R:", [np.round(r, 6).tolist() for r in ib[:3, :3]])
