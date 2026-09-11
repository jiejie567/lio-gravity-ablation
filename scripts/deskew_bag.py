#!/usr/bin/env python3
"""方法L+: 用原始陀螺(仅测量,不融合)对 os1 点云做旋转去畸变,输出新 bag。
每点绕扫描末端参考系旋转对齐,然后把 t 字段清零(下游 KISS-ICP 不再去畸变)。
平移去畸变原理上需要速度(融合产物),故不做——这是"测量级IMU"的信息论边界。
用法: deskew_bag.py <in.bag> <out.bag> [points_topic] [imu_topic]
"""
import sys
import numpy as np
import rosbag
from scipy.spatial.transform import Rotation

in_bag, out_bag = sys.argv[1], sys.argv[2]
pts_topic = sys.argv[3] if len(sys.argv) > 3 else "/os_cloud_node/points"
imu_topic = sys.argv[4] if len(sys.argv) > 4 else "/os_cloud_node/imu"

# 1. 读全部 IMU
imu_t, imu_w = [], []
with rosbag.Bag(in_bag) as bag:
    for _, m, _ in bag.read_messages(topics=[imu_topic]):
        imu_t.append(m.header.stamp.to_sec())
        imu_w.append([m.angular_velocity.x, m.angular_velocity.y, m.angular_velocity.z])
imu_t = np.array(imu_t); imu_w = np.array(imu_w)
print(f"IMU: {len(imu_t)} samples")


def rot_scan(t0, t1, ts_rel):
    """对相对时间 ts_rel(秒,相对t0)的每点,给出 R(点时刻->扫描末端t1) 的旋转对象数组。
    在 [t0,t1] 上积分陀螺得到姿态轨迹 R_k(相对t0),末端 R_end;每点插值 R_p,
    返回 R_end^T... 即把点从其采样时刻姿态转到末端姿态: p' = (R_end^{-1} R_p)^{-1} ...
    实现: q(t) 分段常角速度积分;R_corr(τ) = R(τ→end) = R_end · R_τ^{-1}。"""
    mask = (imu_t >= t0 - 0.02) & (imu_t <= t1 + 0.02)
    tt = imu_t[mask]; ww = imu_w[mask]
    if len(tt) < 3:
        return None
    # 姿态轨迹(相对该扫描开头)
    Rs = [Rotation.identity()]
    for i in range(1, len(tt)):
        dt = tt[i] - tt[i-1]
        Rs.append(Rs[-1] * Rotation.from_rotvec(ww[i-1] * dt))
    R_end = Rs[-1]
    # 每点: 找所属 imu 区间,取区间起点姿态(0.01s 内小角度,足够)
    idx = np.clip(np.searchsorted(tt, t0 + ts_rel) - 1, 0, len(Rs) - 1)
    out = np.empty((len(ts_rel), 3, 3))
    uniq = np.unique(idx)
    for k in uniq:
        Rc = (R_end * Rs[k].inv()).as_matrix()   # R(τ_k -> end)
        out[idx == k] = Rc
    return out


n_done = 0
with rosbag.Bag(in_bag) as ib, rosbag.Bag(out_bag, "w") as ob:
    for topic, m, bt in ib.read_messages(topics=[pts_topic, imu_topic]):
        if topic == imu_topic:
            ob.write(topic, m, bt)
            continue
        step = m.point_step
        toff = {f.name: f.offset for f in m.fields}
        buf = bytearray(m.data)
        arr = np.frombuffer(buf, dtype=np.uint8).reshape(-1, step)
        xyz = np.stack([arr[:, toff[c]:toff[c]+4].copy().view(np.float32).ravel()
                        for c in ("x", "y", "z")], axis=1).astype(np.float64)
        trel = arr[:, toff["t"]:toff["t"]+4].copy().view(np.uint32).ravel().astype(np.float64) / 1e9
        t0 = m.header.stamp.to_sec()          # MCD: header = 扫描末端? 我们实测=起始+点t相对起始
        Rcs = rot_scan(t0, t0 + trel.max() if trel.max() > 0 else t0 + 0.1, trel)
        if Rcs is not None:
            good = np.isfinite(xyz).all(axis=1)
            xyz[good] = np.einsum("nij,nj->ni", Rcs[good], xyz[good])
        # 写回 xyz,t 清零
        for ci, c in enumerate(("x", "y", "z")):
            arr[:, toff[c]:toff[c]+4] = np.ascontiguousarray(
                xyz[:, ci].astype(np.float32)).view(np.uint8).reshape(-1, 4)
        arr[:, toff["t"]:toff["t"]+4] = 0
        m.data = bytes(buf)
        ob.write(topic, m, bt)
        n_done += 1
        if n_done % 500 == 0:
            print(f"  {n_done} scans...")
print(f"done: {n_done} scans -> {out_bag}")
