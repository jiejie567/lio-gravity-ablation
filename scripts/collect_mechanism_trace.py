#!/usr/bin/env python3
"""Generate the paired nominal mechanism-trace summary used by Fig. 3b."""
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
SEQUENCE = "ntu_night_04_os1"
RUNS = {"Online": "A", "FixG": "RED21"}
OUT = ROOT / "report" / "mechanism_trace.json"


def main():
    paths = {
        label: ROOT / "results" / SEQUENCE / run / "state_log.csv"
        for label, run in RUNS.items()
    }
    for path in paths.values():
        if not path.exists():
            raise FileNotFoundError(f"mechanism trace missing: {path}")

    online = pd.read_csv(paths["Online"])
    fixg = pd.read_csv(paths["FixG"])
    required = {"t", "pz", "gx", "gy", "gz"}
    if not required.issubset(online.columns) or not required.issubset(fixg.columns):
        raise ValueError("mechanism trace lacks required state fields")
    timestamps_match = len(online) == len(fixg) and np.allclose(
        online["t"].to_numpy(), fixg["t"].to_numpy(), atol=1e-9
    )
    if not timestamps_match:
        raise ValueError("Online/FixG mechanism traces are not timestamp-paired")

    gravity = online[["gx", "gy", "gz"]].to_numpy()
    gravity /= np.linalg.norm(gravity, axis=1, keepdims=True)
    gravity_angle = np.degrees(np.arccos(np.clip(gravity @ gravity[0], -1, 1)))
    paired_z_sep = np.abs(
        online["pz"].to_numpy() - fixg["pz"].to_numpy()
    )
    duration_s = float(online["t"].iloc[-1] - online["t"].iloc[0])

    payload = {
        "schema_version": 1,
        "sequence": SEQUENCE,
        "runs": RUNS,
        "admission": {
            "timestamps_exact": True,
            "frames_each": int(len(online)),
        },
        "metrics": {
            "duration_s": duration_s,
            "online_gravity_wander_max_deg": float(np.max(gravity_angle)),
            "paired_z_separation_max_m": float(np.max(paired_z_sep)),
        },
    }
    OUT.write_text(json.dumps(payload, indent=2) + "\n")
    print(OUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
