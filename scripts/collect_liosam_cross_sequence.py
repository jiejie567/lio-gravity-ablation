#!/usr/bin/env python3
"""Combine admissible full-sequence LIO-SAM 2x2 ablations."""

from __future__ import annotations

import json
import sys
from pathlib import Path


METRICS = ("rmse_z_m", "ate_rmse_m")
EFFECTS = {
    "estimate_g_given_ba": ("GE-BA", "FG-BA"),
    "estimate_g_given_b0": ("GE-B0", "FG-B0"),
    "fix_ba_given_fg": ("FG-B0", "FG-BA"),
    "fix_ba_given_ge": ("GE-B0", "GE-BA"),
    "fix_both_vs_stock": ("FG-B0", "FG-BA"),
}


def main() -> int:
    if len(sys.argv) < 4:
        print(
            f"usage: {sys.argv[0]} <full-result.json> <full-result.json> [more ...] <output.json>",
            file=sys.stderr,
        )
        return 2

    inputs = [Path(value) for value in sys.argv[1:-1]]
    output = Path(sys.argv[-1])
    sequences = [json.loads(path.read_text()) for path in inputs]
    combined: dict[str, object] = {
        "status": "two_full_sequences_valid_descriptive_only",
        "inference": (
            "Cross-sequence descriptive evidence only; n=2 is insufficient for "
            "a paired significance or equivalence claim."
        ),
        "baseline": "FG-BA (stock LIO-SAM structure)",
        "sequences": sequences,
        "effects": {},
    }

    for effect_name, (numerator, denominator) in EFFECTS.items():
        effect: dict[str, object] = {"contrast": f"{numerator} minus {denominator}"}
        for metric in METRICS:
            per_sequence = []
            for sequence in sequences:
                runs = sequence["runs"]
                absolute = runs[numerator][metric] - runs[denominator][metric]
                percent = (runs[numerator][metric] / runs[denominator][metric] - 1.0) * 100.0
                per_sequence.append(
                    {
                        "sequence": sequence["sequence"],
                        "absolute_difference_m": absolute,
                        "percent_difference": percent,
                    }
                )
            percentages = [item["percent_difference"] for item in per_sequence]
            absolutes = [item["absolute_difference_m"] for item in per_sequence]
            effect[metric] = {
                "per_sequence": per_sequence,
                "percent_range": [min(percentages), max(percentages)],
                "absolute_range_m": [min(absolutes), max(absolutes)],
            }
        combined["effects"][effect_name] = effect

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(combined, indent=2) + "\n")
    print(json.dumps(combined, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
