#!/usr/bin/env python3
"""检查 TIERS bag: 全部 topic、Avia/Mid360 PointCloud2 的字段结构(有无每点时间戳)、
IMU 频率、GT topic。决定 FAST-LIO 预处理如何适配。"""
import sys
import rosbag

path = sys.argv[1]
bag = rosbag.Bag(path)
info = bag.get_type_and_topic_info()[1]
print("== topics ==")
for t, ti in sorted(info.items()):
    print(f"  {t:45s} {ti.msg_type:35s} {ti.message_count:7d} msgs")

for topic in info:
    if "lidar" in topic and info[topic].msg_type == "sensor_msgs/PointCloud2":
        for _, msg, _ in bag.read_messages(topics=[topic]):
            print(f"\n== {topic} fields ==")
            for f in msg.fields:
                print(f"  name={f.name:15s} offset={f.offset:3d} datatype={f.datatype} count={f.count}")
            print(f"  point_step={msg.point_step}, width={msg.width}, height={msg.height}")
            print(f"  header.stamp={msg.header.stamp.to_sec():.6f}, frame_id={msg.header.frame_id}")
            break
bag.close()
