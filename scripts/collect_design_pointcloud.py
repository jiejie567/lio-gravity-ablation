#!/usr/bin/env python3
"""Extract the audited FAST-LIO scan used in the design figure.

Fig. 2 is qualitative, but its point cloud must still be traceable. This
collector slices one post-preprocessing, deskewed dense scan from FAST-LIO's
saved PCD output, transforms it back to the LiDAR frame, and verifies that its
intensity multiset exactly matches the returns retained from the source
PointCloud2 message by the run's preprocessing settings.
"""
import argparse
import ast
import csv
import hashlib
import json
import re
from pathlib import Path

import numpy as np
from rosbags.rosbag1 import Reader
from rosbags.typesys import Stores, get_typestore


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BAG = ROOT / "data" / "mcd" / "ntu_day_10" / "os1.bag"
DEFAULT_TOPIC = "/os_cloud_node/points"
DEFAULT_RUN = ROOT / "results" / "ntu_day_10_os1" / "A"
DEFAULT_MAP_PCD = DEFAULT_RUN / "map.pcd"
DEFAULT_STATE_LOG = DEFAULT_RUN / "state_log.csv"
DEFAULT_RUN_META = DEFAULT_RUN / "run_meta.txt"
DEFAULT_EXP_CONFIG = DEFAULT_RUN / "exp_params.yaml"
DEFAULT_BASE_CONFIG = ROOT / "configs" / "mcd_atv_os1_imuint_off01.yaml"
DEFAULT_RVIZ_CONFIG = (
    ROOT / "catkin_ws" / "src" / "FAST_LIO" / "rviz_cfg" / "loam_livox.rviz"
)
DEFAULT_STATE_ROW = 240
MAX_RELATIVE_TIME_MS = 100.0
RANGE_LIMIT_M = 20.0
FOV_HALF_ANGLE_DEG = 60.0


def relative_source(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.name


def read_scalar(path: Path, key: str) -> float:
    match = re.search(
        rf"^\s*{re.escape(key)}\s*:\s*([-+0-9.eE]+)",
        path.read_text(),
        flags=re.MULTILINE,
    )
    if not match:
        raise RuntimeError(f"missing {key!r} in {path}")
    return float(match.group(1))


def read_vector(path: Path, key: str, size: int) -> np.ndarray:
    match = re.search(
        rf"^\s*{re.escape(key)}\s*:\s*(\[[^\]]+\])",
        path.read_text(),
        flags=re.MULTILINE,
    )
    if not match:
        raise RuntimeError(f"missing {key!r} in {path}")
    values = np.asarray(ast.literal_eval(match.group(1)), dtype=np.float64)
    if values.size != size:
        raise RuntimeError(f"{key!r} in {path} has {values.size} values, not {size}")
    return values


def read_fastlio_rviz_renderer(path: Path, display_name: str = "surround"):
    """Read the enabled FAST-LIO ROS1 PointCloud2 display without PyYAML."""
    lines = path.read_text().splitlines()
    name_line = next(
        (index for index, line in enumerate(lines)
         if line.strip() == f"Name: {display_name}"),
        None,
    )
    if name_line is None:
        raise RuntimeError(f"RViz display {display_name!r} not found in {path}")
    start = next(
        (index for index in range(name_line, -1, -1)
         if re.match(r"^        - ", lines[index])),
        None,
    )
    if start is None:
        raise RuntimeError(f"cannot locate start of RViz display {display_name!r}")
    end = next(
        (index for index in range(name_line + 1, len(lines))
         if re.match(r"^        - ", lines[index])),
        len(lines),
    )
    block = "\n".join(lines[start:end])

    def scalar(key):
        match = re.search(
            rf"^\s+(?:-\s+)?{re.escape(key)}:\s*(.*?)\s*$",
            block,
            flags=re.MULTILINE,
        )
        if not match:
            raise RuntimeError(
                f"RViz display {display_name!r} is missing {key!r}"
            )
        value = match.group(1)
        if value in {"true", "false"}:
            return value == "true"
        try:
            numeric = float(value)
            return int(numeric) if numeric.is_integer() else numeric
        except ValueError:
            return value

    background_match = re.search(
        r"^\s+Background Color:\s*(\d+);\s*(\d+);\s*(\d+)\s*$",
        path.read_text(),
        flags=re.MULTILINE,
    )
    fixed_frame_match = re.search(
        r"^\s+Fixed Frame:\s*(.*?)\s*$",
        path.read_text(),
        flags=re.MULTILINE,
    )
    if not background_match or not fixed_frame_match:
        raise RuntimeError(f"RViz global options are incomplete in {path}")
    return {
        "implementation": "ROS1 RViz IntensityPCTransformer",
        "rviz_config": relative_source(path),
        "display_name": scalar("Name"),
        "topic": scalar("Topic"),
        "fixed_frame": fixed_frame_match.group(1),
        "color_transformer": scalar("Color Transformer"),
        "channel_name": scalar("Channel Name"),
        "autocompute_intensity_bounds": scalar(
            "Autocompute Intensity Bounds"),
        "use_rainbow": scalar("Use rainbow"),
        "invert_rainbow": scalar("Invert Rainbow"),
        "alpha": float(scalar("Alpha")),
        "style": scalar("Style"),
        "size_pixels": int(scalar("Size (Pixels)")),
        "background_rgb": [int(value) for value in background_match.groups()],
    }


def read_state_rows(path: Path):
    with path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise RuntimeError(f"empty state log: {path}")
    required = {"t", "px", "py", "pz", "qx", "qy", "qz", "qw"}
    missing = required - rows[0].keys()
    if missing:
        raise RuntimeError(f"state log missing columns: {sorted(missing)}")
    return [{key: float(value) for key, value in row.items()} for row in rows]


def quaternion_matrix(qx: float, qy: float, qz: float, qw: float):
    quaternion = np.asarray((qx, qy, qz, qw), dtype=np.float64)
    norm = np.linalg.norm(quaternion)
    if not np.isfinite(norm) or norm < 1e-12:
        raise RuntimeError("invalid state quaternion")
    x, y, z, w = quaternion / norm
    return np.asarray([
        [1 - 2 * (y*y + z*z), 2 * (x*y - z*w), 2 * (x*z + y*w)],
        [2 * (x*y + z*w), 1 - 2 * (x*x + z*z), 2 * (y*z - x*w)],
        [2 * (x*z - y*w), 2 * (y*z + x*w), 1 - 2 * (x*x + y*y)],
    ])


def pointcloud_fields(msg):
    fields = {field.name: int(field.offset) for field in msg.fields}
    missing = {"x", "y", "z", "intensity", "t"} - fields.keys()
    if missing:
        raise RuntimeError(f"PointCloud2 missing fields: {sorted(missing)}")
    count = int(msg.height) * int(msg.width)
    point_step = int(msg.point_step)
    packed = np.frombuffer(msg.data, dtype=np.uint8).reshape(count, point_step)
    f4 = ">f4" if msg.is_bigendian else "<f4"
    u4 = ">u4" if msg.is_bigendian else "<u4"

    def unpack(name, dtype, size):
        offset = fields[name]
        return packed[:, offset:offset + size].copy().view(dtype).reshape(-1)

    xyz = np.column_stack([unpack(name, f4, 4) for name in ("x", "y", "z")])
    intensity = unpack("intensity", f4, 4)
    relative_time_ns = unpack("t", u4, 4)
    return xyz, intensity, relative_time_ns


def scan_records(
        bag: Path,
        topic: str,
        state_times,
        point_filter_num: int,
        blind_m: float):
    typestore = get_typestore(Stores.ROS1_NOETIC)
    target_time = float(max(state_times))
    records = []
    target_candidates = {float(time): (float("inf"), None) for time in state_times}
    message_type = None
    with Reader(bag) as reader:
        connections = [connection for connection in reader.connections
                       if connection.topic == topic]
        if len(connections) != 1:
            raise RuntimeError(
                f"expected one {topic!r} connection, found {len(connections)}"
            )
        for index, (connection, timestamp, rawdata) in enumerate(
                reader.messages(connections=connections)):
            msg = typestore.deserialize_ros1(rawdata, connection.msgtype)
            xyz, intensity, relative_time_ns = pointcloud_fields(msg)
            indices = np.arange(len(xyz))
            range_sq = np.einsum("ij,ij->i", xyz, xyz)
            keep = (
                (indices % point_filter_num == 0)
                & (range_sq >= blind_m * blind_m)
                & (relative_time_ns / 1e6 <= MAX_RELATIVE_TIME_MS)
            )
            selected_intensity = intensity[keep].astype(np.float32, copy=False)
            valid_times = relative_time_ns[
                relative_time_ns / 1e6 <= MAX_RELATIVE_TIME_MS]
            if valid_times.size == 0:
                raise RuntimeError(f"raw scan {index} has no valid relative times")
            end_time = timestamp / 1e9 + float(valid_times.max()) / 1e9
            records.append({
                "index": index,
                "end_time": end_time,
                "count": int(keep.sum()),
            })
            for state_time in state_times:
                distance = abs(end_time - float(state_time))
                if distance < target_candidates[float(state_time)][0]:
                    target_candidates[float(state_time)] = (
                        distance,
                        selected_intensity.copy(),
                    )
            message_type = connection.msgtype
            if end_time > target_time + 0.15:
                break
    return records, target_candidates, message_type


def read_binary_pcd(path: Path):
    header = {}
    with path.open("rb") as stream:
        while True:
            line = stream.readline()
            if not line:
                raise RuntimeError(f"truncated PCD header: {path}")
            parts = line.decode("ascii").strip().split()
            if parts:
                header[parts[0]] = parts[1:]
            if parts and parts[0] == "DATA":
                data_offset = stream.tell()
                break
    fields = header.get("FIELDS", [])
    sizes = list(map(int, header.get("SIZE", [])))
    types = header.get("TYPE", [])
    counts = list(map(int, header.get("COUNT", ["1"] * len(fields))))
    if header.get("DATA") != ["binary"]:
        raise RuntimeError("design source must be a binary PCD")
    if not (len(fields) == len(sizes) == len(types) == len(counts)):
        raise RuntimeError("inconsistent PCD field metadata")
    if any(size != 4 or kind != "F" or count != 1
           for size, kind, count in zip(sizes, types, counts)):
        raise RuntimeError("design source must contain scalar float32 PCD fields")
    missing = {"x", "y", "z", "intensity"} - set(fields)
    if missing:
        raise RuntimeError(f"PCD missing fields: {sorted(missing)}")
    total = int(header["POINTS"][0])
    data = np.memmap(
        path, dtype="<f4", mode="r", offset=data_offset,
        shape=(total, len(fields)),
    )
    return fields, data


def extract_fastlio_scan(
        bag: Path,
        topic: str,
        map_pcd: Path,
        state_log: Path,
        exp_config: Path,
        base_config: Path,
        state_row_index: int):
    rows = read_state_rows(state_log)
    if not 0 <= state_row_index < len(rows):
        raise IndexError(f"state row {state_row_index} is outside {state_log}")
    first_row = rows[0]
    target_row = rows[state_row_index]
    point_filter_num = int(read_scalar(exp_config, "point_filter_num"))
    blind_m = read_scalar(base_config, "blind")
    records, candidates, message_type = scan_records(
        bag,
        topic,
        (first_row["t"], target_row["t"]),
        point_filter_num,
        blind_m,
    )
    first_record = min(records, key=lambda item: abs(item["end_time"] - first_row["t"]))
    target_record = min(
        records, key=lambda item: abs(item["end_time"] - target_row["t"]))
    first_error = abs(first_record["end_time"] - first_row["t"])
    target_error = abs(target_record["end_time"] - target_row["t"])
    if first_error > 0.03 or target_error > 0.03:
        raise RuntimeError(
            "FAST-LIO state timestamps do not match source scans: "
            f"{first_error:.6f}s, {target_error:.6f}s"
        )
    if target_record["index"] < first_record["index"]:
        raise RuntimeError("target raw scan precedes the first FAST-LIO output scan")
    count_by_index = {record["index"]: record["count"] for record in records}
    expected_indices = range(first_record["index"], target_record["index"])
    missing = [index for index in expected_indices if index not in count_by_index]
    if missing:
        raise RuntimeError(f"missing raw scan counts before target: {missing[:5]}")
    start = sum(count_by_index[index] for index in expected_indices)
    stop = start + target_record["count"]

    fields, pcd = read_binary_pcd(map_pcd)
    if stop > len(pcd):
        raise RuntimeError("target FAST-LIO scan lies outside saved PCD")
    segment = np.asarray(pcd[start:stop]).copy()
    field_index = {name: fields.index(name) for name in fields}
    world_xyz = segment[:, [field_index[name] for name in ("x", "y", "z")]]
    intensity = segment[:, field_index["intensity"]].astype(np.float32, copy=False)
    raw_intensity = candidates[float(target_row["t"])][1]
    intensity_matches = (
        raw_intensity is not None
        and len(intensity) == len(raw_intensity)
        and np.array_equal(np.sort(intensity), np.sort(raw_intensity))
    )
    if not intensity_matches:
        raise RuntimeError(
            "saved FAST-LIO scan intensity does not match retained raw returns"
        )

    state_rotation = quaternion_matrix(
        target_row["qx"], target_row["qy"], target_row["qz"], target_row["qw"])
    state_position = np.asarray(
        [target_row["px"], target_row["py"], target_row["pz"]])
    extrinsic_translation = read_vector(base_config, "extrinsic_T", 3)
    extrinsic_rotation = read_vector(base_config, "extrinsic_R", 9).reshape(3, 3)
    imu_xyz = (world_xyz.astype(np.float64) - state_position) @ state_rotation
    lidar_xyz = (
        (imu_xyz - extrinsic_translation) @ extrinsic_rotation
    ).astype(np.float32)
    if (not np.isfinite(lidar_xyz).all()
            or not np.isfinite(intensity).all()
            or np.any(intensity < 0)):
        raise RuntimeError("extracted FAST-LIO scan contains invalid values")
    provenance = {
        "message_type": message_type,
        "fastlio_state_row_zero_based": state_row_index,
        "raw_scan_index_zero_based": target_record["index"],
        "first_fastlio_raw_scan_index_zero_based": first_record["index"],
        "state_to_raw_end_time_error_s": target_error,
        "point_filter_num": point_filter_num,
        "blind_m": blind_m,
        "max_relative_time_ms": MAX_RELATIVE_TIME_MS,
        "pcd_point_offset": [start, stop],
        "intensity_multiset_matches_retained_raw": True,
    }
    return (
        lidar_xyz,
        intensity,
        target_row["t"] - first_row["t"],
        provenance,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bag", type=Path, default=DEFAULT_BAG)
    parser.add_argument("--topic", default=DEFAULT_TOPIC)
    parser.add_argument("--map-pcd", type=Path, default=DEFAULT_MAP_PCD)
    parser.add_argument("--state-log", type=Path, default=DEFAULT_STATE_LOG)
    parser.add_argument("--run-meta", type=Path, default=DEFAULT_RUN_META)
    parser.add_argument("--exp-config", type=Path, default=DEFAULT_EXP_CONFIG)
    parser.add_argument("--base-config", type=Path, default=DEFAULT_BASE_CONFIG)
    parser.add_argument("--rviz-config", type=Path, default=DEFAULT_RVIZ_CONFIG)
    parser.add_argument("--state-row", type=int, default=DEFAULT_STATE_ROW)
    parser.add_argument("--out-npz", type=Path,
                        default=ROOT / "report" / "design_pointcloud.npz")
    parser.add_argument("--out-json", type=Path,
                        default=ROOT / "report" / "design_pointcloud.json")
    args = parser.parse_args()

    xyz, intensity, relative_time_s, provenance = extract_fastlio_scan(
        args.bag,
        args.topic,
        args.map_pcd,
        args.state_log,
        args.exp_config,
        args.base_config,
        args.state_row,
    )
    horizontal_range = np.linalg.norm(xyz[:, :2], axis=1)
    abs_azimuth = np.abs(np.arctan2(xyz[:, 1], xyz[:, 0]))
    range_mask = horizontal_range < RANGE_LIMIT_M
    fov_mask = abs_azimuth < np.deg2rad(FOV_HALF_ANGLE_DEG)
    intensity_bounds = {
        "nominal": [float(np.min(intensity)), float(np.max(intensity))],
        "range": [
            float(np.min(intensity[range_mask])),
            float(np.max(intensity[range_mask])),
        ],
        "fov": [
            float(np.min(intensity[fov_mask])),
            float(np.max(intensity[fov_mask])),
        ],
    }
    rviz_renderer = read_fastlio_rviz_renderer(args.rviz_config)

    args.out_npz.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.out_npz, xyz=xyz, intensity=intensity)
    digest = hashlib.sha256(args.out_npz.read_bytes()).hexdigest()
    run_meta = args.run_meta.read_text() if args.run_meta.exists() else ""
    commit_match = re.search(r"^fastlio_commit:\s*(\S+)", run_meta, re.MULTILINE)
    manifest = {
        "schema_version": 5,
        "role": "qualitative intervention visualization; not a performance result",
        "source": {
            "dataset": "MCD",
            "sequence": "ntu_day_10_os1",
            "bag": relative_source(args.bag),
            "topic": args.topic,
            "fastlio_run": relative_source(args.state_log.parent),
            "map_pcd": relative_source(args.map_pcd),
            "state_log": relative_source(args.state_log),
            "pointcloud_stage": (
                "FAST-LIO post-preprocessing, deskewed dense scan "
                "(feats_undistort)"
            ),
            "fastlio_commit": commit_match.group(1) if commit_match else None,
            "relative_time_s": relative_time_s,
            **provenance,
        },
        "interventions": {
            "range_limit_m": RANGE_LIMIT_M,
            "fov_half_angle_deg": FOV_HALF_ANGLE_DEG,
            "dropout_gap_s": [1, 2, 3, 5],
        },
        "counts": {
            "finite_points": int(len(xyz)),
            "range_retained": int(range_mask.sum()),
            "fov_retained": int(fov_mask.sum()),
        },
        "visualization": {
            "common_xy_limit_m": 45.0,
            "z_limits_m": [-3.0, 8.0],
            "max_display_points": 24000,
            "random_seed": 2027,
            "intensity_field": "intensity",
            "intensity_bounds": intensity_bounds,
            "renderer": rviz_renderer,
            "note": (
                "A common deterministic display subset is used. Each admitted "
                "cloud is colored with the bundled FAST-LIO ROS1 RViz display's "
                "linear automatic intensity bounds and native rainbow transfer."
            ),
        },
        "artifact": {
            "path": args.out_npz.relative_to(ROOT).as_posix(),
            "sha256": digest,
        },
    }
    args.out_json.write_text(json.dumps(manifest, indent=2) + "\n")
    print(args.out_npz)
    print(args.out_json)


if __name__ == "__main__":
    main()
