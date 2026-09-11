#!/usr/bin/env python3
"""从 bag 提取 PoseStamped 真值 topic 为 TUM 格式文本(容器内运行)。
用法: extract_gt_from_bag.py <bag> <topic> <out.txt>"""
import sys
import rosbag

bag_path, topic, out = sys.argv[1], sys.argv[2], sys.argv[3]
n = 0
with open(out, "w") as f, rosbag.Bag(bag_path) as bag:
    for _, msg, _ in bag.read_messages(topics=[topic]):
        p, q = msg.pose.position, msg.pose.orientation
        f.write(f"{msg.header.stamp.to_sec():.9f} {p.x:.6f} {p.y:.6f} {p.z:.6f} "
                f"{q.x:.9f} {q.y:.9f} {q.z:.9f} {q.w:.9f}\n")
        n += 1
print(f"{out}: {n} poses")
