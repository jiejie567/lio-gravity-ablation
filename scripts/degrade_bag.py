#!/usr/bin/env python3
"""受控退化 rosbag 生成器(宿主机运行,纯 python 无需 ROS)。

对现有序列做单变量微弱退化,考察配准通道弱化时 A(在线重力)vs C(全冻结)是否分离:
  range<R>   点云限距: 只保留距离 < R 米的点(去掉长基线约束)
  fov<D>     只保留前向 ±D° 方位扇区(走廊式方向性退化)
  drop<G>x<P>  每 P 秒挖掉 G 秒的雷达帧(间歇丢帧,IMU 独自递推)

用法:
  degrade_bag.py <in.bag> <out.bag> range20
  degrade_bag.py <in.bag> <out.bag> fov60
  degrade_bag.py <in.bag> <out.bag> drop1x20
IMU 与其他 topic 原样拷贝;点云只改 data/width,字段布局不动(t/ring 等保留)。
"""
import argparse
import re
import numpy as np
from rosbags.rosbag1 import Reader, Writer
from rosbags.typesys import Stores, get_typestore

TS = get_typestore(Stores.ROS1_NOETIC)
PC2 = "sensor_msgs/msg/PointCloud2"


def parse_mode(mode):
    m = re.fullmatch(r"range(\d+(?:\.\d+)?)", mode)
    if m:
        return ("range", float(m.group(1)))
    m = re.fullmatch(r"fov(\d+(?:\.\d+)?)", mode)
    if m:
        return ("fov", float(m.group(1)))
    m = re.fullmatch(r"drop(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)", mode)
    if m:
        return ("drop", (float(m.group(1)), float(m.group(2))))
    raise SystemExit(f"未知模式: {mode}")


def filter_cloud(msg, kind, param):
    """结构化字节级过滤: x,y,z 是 offset 0/4/8 的 float32(os1 与 mid360 均如此)"""
    step = msg.point_step
    n = msg.width * msg.height
    raw = np.frombuffer(msg.data, dtype=np.uint8).reshape(n, step)
    xyz = raw[:, 0:12].copy().view(np.float32).reshape(n, 3)
    if kind == "range":
        r = np.linalg.norm(xyz, axis=1)
        keep = np.isfinite(r) & (r < param)
    else:  # fov
        az = np.degrees(np.arctan2(xyz[:, 1], xyz[:, 0]))
        keep = np.isfinite(az) & (np.abs(az) < param)
    kept = raw[keep]
    msg.height = 1
    msg.width = kept.shape[0]
    msg.row_step = kept.shape[0] * step
    msg.data = kept.reshape(-1)
    return msg, n, int(keep.sum())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("src")
    parser.add_argument("dst")
    parser.add_argument("mode")
    parser.add_argument(
        "--drop-start-sec",
        type=float,
        default=None,
        help=(
            "absolute elapsed time of the first dropout start; subsequent gaps "
            "repeat at the period encoded by drop<G>x<P>"
        ),
    )
    args = parser.parse_args()
    src, dst, mode = args.src, args.dst, args.mode
    kind, param = parse_mode(mode)
    if args.drop_start_sec is not None and kind != "drop":
        parser.error("--drop-start-sec is valid only for drop<G>x<P>")
    if args.drop_start_sec is not None and args.drop_start_sec < 0.0:
        parser.error("--drop-start-sec must be non-negative")
    tot_in = tot_out = dropped_msgs = 0
    t0 = None
    with Reader(src) as reader, Writer(dst) as writer:
        conns = {}
        for c in reader.connections:
            conns[c.id] = writer.add_connection(
                c.topic, c.msgtype, typestore=TS,
                callerid=c.ext.callerid, latching=c.ext.latching)
        for c, timestamp, rawdata in reader.messages():
            if c.msgtype != PC2:
                writer.write(conns[c.id], timestamp, rawdata)
                continue
            if t0 is None:
                t0 = timestamp
            if kind == "drop":
                gap, period = param
                elapsed = (timestamp - t0) / 1e9
                if args.drop_start_sec is None:
                    phase = elapsed % period
                    # 兼容既有数据:每周期的最后 gap 秒挖掉整帧。
                    should_drop = phase > period - gap
                else:
                    # 显式第一空窗起点用于 phase 鲁棒性；开始前不删除任何帧。
                    should_drop = (
                        elapsed >= args.drop_start_sec
                        and ((elapsed - args.drop_start_sec) % period) < gap
                    )
                if should_drop:
                    dropped_msgs += 1
                    continue
                writer.write(conns[c.id], timestamp, rawdata)
                tot_in += 1
                continue
            msg = TS.deserialize_ros1(rawdata, c.msgtype)
            msg, n_in, n_out = filter_cloud(msg, kind, param)
            tot_in += n_in
            tot_out += n_out
            writer.write(conns[c.id], timestamp, TS.serialize_ros1(msg, c.msgtype))
    if kind == "drop":
        start = "legacy-period-end" if args.drop_start_sec is None else f"{args.drop_start_sec:g}s"
        print(f"[{mode}, first-start={start}] 保留帧 {tot_in}, 挖掉帧 {dropped_msgs}")
    else:
        print(f"[{mode}] 点保留率 {100.0 * tot_out / max(tot_in, 1):.1f}% ({tot_out}/{tot_in})")


if __name__ == "__main__":
    main()
