#!/usr/bin/env python3
"""检查 MCD os1 bag 的时间戳约定(容器内运行)。
对比: 点云 header.stamp、点内相对时间 t 的范围、相邻 IMU 的 header.stamp。"""
import rosbag, struct, sys
import numpy as np

path = sys.argv[1] if len(sys.argv) > 1 else "/work/data/mcd/tuhh_day_04/os1.bag"
bag = rosbag.Bag(path)

n_pc = 0
imu_around = []
pc_stamps = []
for topic, msg, bt in bag.read_messages(topics=["/os_cloud_node/points", "/os_cloud_node/imu"]):
    if topic.endswith("imu"):
        imu_around.append(msg.header.stamp.to_sec())
        continue
    n_pc += 1
    if n_pc < 5:
        continue
    st = msg.header.stamp.to_sec()
    pc_stamps.append(st)
    if n_pc == 5:
        # 解析 t 字段 (uint32) 与 ring
        toff = {f.name: f.offset for f in msg.fields}
        step = msg.point_step
        ts = []
        for i in range(0, min(msg.width * msg.height, 60000), 97):
            t = struct.unpack_from("<I", msg.data, i * step + toff["t"])[0]
            ts.append(t)
        ts = np.array(ts, dtype=np.float64)
        print(f"点云#5 header.stamp = {st:.6f}")
        print(f"点内 t 范围: [{ts.min():.0f}, {ts.max():.0f}] ns  = [{ts.min()/1e9:.4f}, {ts.max()/1e9:.4f}] s")
        print(f"bag 收包时刻 (rosbag time) = {bt.to_sec():.6f}, 与 header.stamp 差 = {bt.to_sec()-st:.4f} s")
    if n_pc >= 8:
        break
bag.close()

pc_stamps = np.array(pc_stamps)
imu_around = np.array(imu_around)
if len(pc_stamps) >= 2:
    print(f"相邻点云 stamp 间隔: {np.diff(pc_stamps)} s")
for st in pc_stamps[:2]:
    near = imu_around[np.argmin(np.abs(imu_around - st))]
    print(f"点云 stamp {st:.4f} 最近的 IMU stamp: {near:.4f} (差 {near-st:+.4f} s)")
print(f"IMU stamp 范围: [{imu_around.min():.4f}, {imu_around.max():.4f}]")
print(f"IMU 平均间隔: {np.mean(np.diff(np.sort(imu_around)))*1000:.2f} ms")
