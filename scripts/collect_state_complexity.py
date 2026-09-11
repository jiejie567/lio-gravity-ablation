#!/usr/bin/env python3
"""Derive state-only scaling estimates from the four compiled manifolds.

This is a source-level arithmetic estimate, not an end-to-end timing result.
The error-state dimension is parsed from each variant's df_dx signature so the
paper never hand-copies the dimensions or their derived percentages.
"""
import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
HEADERS = {
    "Online": ROOT / "catkin_ws" / "src" / "FAST_LIO" / "include" / "use-ikfom.hpp",
    "FixG": ROOT / "catkin_ws" / "src" / "FAST_LIO" / "include" / "use-ikfom-redg.hpp",
    "FixBa": ROOT / "catkin_ws" / "src" / "FAST_LIO" / "include" / "use-ikfom-redb.hpp",
    "FixG+Ba": ROOT / "catkin_ws" / "src" / "FAST_LIO" / "include" / "use-ikfom-red.hpp",
}
OUT = ROOT / "report" / "state_complexity.json"


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def error_state_dimension(path: Path) -> int:
    text = path.read_text()
    match = re.search(
        r"Eigen::Matrix\s*<\s*double\s*,\s*\d+\s*,\s*(\d+)\s*>\s*df_dx\s*\(",
        text,
    )
    if not match:
        raise RuntimeError(f"cannot parse df_dx error-state dimension from {path}")
    return int(match.group(1))


def main():
    dimensions = {name: error_state_dimension(path)
                  for name, path in HEADERS.items()}
    baseline = dimensions["Online"]
    if dimensions != {"Online": 23, "FixG": 21, "FixBa": 20, "FixG+Ba": 18}:
        raise RuntimeError(f"unexpected compiled dimensions: {dimensions}")

    estimates = {}
    for name, dimension in dimensions.items():
        estimates[name] = {
            "dimension": dimension,
            "quadratic_reduction_pct_vs_online": (
                100.0 * (1.0 - (dimension / baseline) ** 2)
            ),
            "cubic_reduction_pct_vs_online": (
                100.0 * (1.0 - (dimension / baseline) ** 3)
            ),
        }

    payload = {
        "schema_version": 1,
        "role": "source-derived state-only arithmetic scaling estimate",
        "end_to_end_profiled": False,
        "sources": {
            name: {
                "path": relative(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for name, path in HEADERS.items()
        },
        "baseline": "Online",
        "estimates": estimates,
        "assumptions": [
            "quadratic and cubic dense algebra scale as d^2 and d^3",
            "only the state-side component is represented",
        ],
        "excluded_from_estimate": [
            "point-cloud preprocessing",
            "nearest-neighbor search",
            "residual construction",
            "map maintenance",
            "system and middleware overhead",
        ],
    }
    OUT.write_text(json.dumps(payload, indent=2) + "\n")
    print(OUT)


if __name__ == "__main__":
    main()
