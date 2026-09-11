#!/usr/bin/env python3
"""Compute a ba initialization that exactly compensates a gravity tilt.

FAST-LIO propagates acceleration through ``g - R @ ba``.  Given the first
logged baseline state and the same tilt convention used by laserMapping.cpp,
this script returns an absolute body-frame ba initialization for which that
combination is unchanged at the intervention boundary.
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial.transform import Rotation


def compensated_ba(state_log: Path, angle_deg: float) -> np.ndarray:
    row = pd.read_csv(state_log).dropna().iloc[0]
    gravity = row[["gx", "gy", "gz"]].to_numpy(dtype=float)
    ba = row[["bax", "bay", "baz"]].to_numpy(dtype=float)
    rotation = Rotation.from_quat(
        row[["qx", "qy", "qz", "qw"]].to_numpy(dtype=float)
    ).as_matrix()

    axis = np.cross(gravity, np.array([1.0, 0.0, 0.0]))
    if np.linalg.norm(axis) < 1e-6:
        axis = np.cross(gravity, np.array([0.0, 1.0, 0.0]))
    axis /= np.linalg.norm(axis)
    tilted = Rotation.from_rotvec(axis * np.deg2rad(angle_deg)).apply(gravity)

    # tilted - R @ ba_new == gravity - R @ ba
    return ba + rotation.T @ (tilted - gravity)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("state_log", type=Path)
    parser.add_argument("angle_deg", type=float)
    args = parser.parse_args()
    value = compensated_ba(args.state_log, args.angle_deg)
    print(" ".join(f"{component:.12f}" for component in value))


if __name__ == "__main__":
    main()
