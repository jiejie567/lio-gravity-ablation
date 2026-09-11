#!/usr/bin/env python3
"""量化一条序列的运动激励水平(容器内运行)。
输入: GT pose CSV + bag 的 IMU topic。输出 roll/pitch 幅度、角速度、加速度统计。"""
import sys
import numpy as np
from scipy.spatial.transform import Rotation
import rosbag

gt_path, bag_path, imu_topic = sys.argv[1], sys.argv[2], sys.argv[3]

rows = []
for line in open(gt_path):
    try:
        v = [float(x) for x in line.replace(",", " ").split()]
    except ValueError:
        continue
    if len(v) >= 9:
        rows.append(v[1:9])
a = np.array(rows)
eul = Rotation.from_quat(a[:, 4:8]).as_euler("ZYX", degrees=True)  # yaw,pitch,roll
dur = a[-1, 0] - a[0, 0]
dist = np.sum(np.linalg.norm(np.diff(a[:, 1:4], axis=0), axis=1))
print(f"== GT: 时长 {dur:.0f}s, 路径长 {dist:.0f}m")
for name, i in [("roll", 2), ("pitch", 1)]:
    x = eul[:, i] - np.mean(eul[:, i])
    print(f"GT {name}: std {np.std(x):.2f} deg, 峰峰值 {x.max()-x.min():.2f} deg")
yaw_rate = np.abs(np.diff(np.unwrap(np.radians(eul[:, 0]))) / np.diff(a[:, 0]))
print(f"GT yaw 速率: 中位 {np.degrees(np.median(yaw_rate)):.1f} deg/s, P95 {np.degrees(np.percentile(yaw_rate,95)):.1f} deg/s")

g = []
w = []
bag = rosbag.Bag(bag_path)
for _, msg, _ in bag.read_messages(topics=[imu_topic]):
    w.append([msg.angular_velocity.x, msg.angular_velocity.y, msg.angular_velocity.z])
    g.append([msg.linear_acceleration.x, msg.linear_acceleration.y, msg.linear_acceleration.z])
bag.close()
w = np.degrees(np.array(w)); g = np.array(g)
print(f"== IMU ({imu_topic}, {len(w)} 帧)")
print(f"gyro |w| : 中位 {np.median(np.linalg.norm(w,axis=1)):.1f} deg/s, P95 {np.percentile(np.linalg.norm(w,axis=1),95):.1f} deg/s")
print(f"gyro xy(roll/pitch 轴) std: {np.std(w[:,0]):.1f}, {np.std(w[:,1]):.1f} deg/s; z(yaw 轴) std: {np.std(w[:,2]):.1f} deg/s")
gn = np.linalg.norm(g, axis=1)
print(f"acc |a|: 均值 {gn.mean():.2f}, std {gn.std():.3f} (单位同源), 非重力分量占比 {gn.std()/gn.mean()*100:.1f}%")
