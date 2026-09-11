#!/usr/bin/env python3
"""扫描 os1 bag 全部点云帧,找: 空帧 / 点内 t 超 100ms 的帧 / header 时间跳变。"""
import rosbag, struct, sys
import numpy as np

path = sys.argv[1]
bag = rosbag.Bag(path)
last_st = None
n = 0
for topic, msg, bt in bag.read_messages(topics=["/os_cloud_node/points"]):
    n += 1
    st = msg.header.stamp.to_sec()
    npts = msg.width * msg.height
    issues = []
    if npts == 0:
        issues.append("EMPTY")
    else:
        toff = {f.name: f.offset for f in msg.fields}
        step = msg.point_step
        ts = np.array([struct.unpack_from("<I", msg.data, i * step + toff["t"])[0]
                       for i in range(0, npts, max(1, npts // 500))], dtype=np.float64)
        frac_bad = float((ts / 1e6 > 100.0).mean())
        if frac_bad > 0:
            issues.append(f"badT {frac_bad*100:.1f}% maxT {ts.max()/1e9:.3f}s")
    if last_st is not None:
        dt = st - last_st
        if dt < 0 or dt > 0.15:
            issues.append(f"stampJump dt={dt:.3f}")
    if issues:
        print(f"#{n} t={st:.3f} (+{st-t0 if n>1 else 0:.1f}s) pts={npts}: {'; '.join(issues)}")
    if n == 1:
        t0 = st
    last_st = st
bag.close()
print(f"total msgs: {n}")
