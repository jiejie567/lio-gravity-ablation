# Claims to evidence

| Question | Authoritative report | Inspectable evidence |
|---|---|---|
| Continuous correction: does removing g affect pose accuracy? | `summary.json`, `equivalence_sensitivity.json`, `strengthening_20260831.json` | Nominal A/RED21/RED20/RED18 states; `_repro0831` pairs; Tables I and stats macros |
| Is the implementation genuinely reduced? | `state_complexity.json` | `catkin_ws/src/FAST_LIO/include/use-ikfom*`, mapping/IMU source variants, `validate_reduced.py`; LIO-SAM `include/lio_sam/ImuAblationFactors.h` and `src/imuPreintegration.cpp` |
| Does correction absence activate utility? | `warm_fixg21.json`, `matched_ape.json`, `summary.json` | Clean/dropout pairs, `warm_fixg_event.csv`, bit-identical pre-switch states, all three original repeats and shifted phases; Fig. 4/Table II |
| Do direction factors always help? | `strengthening_20260831.json`, `liosam_direction.json` | Hall05 and TUHH state × weight × repeat records, odometry and direction residuals; Fig. 5/Table III |
| Does moving-start initialization change the recommendation? | `dynamic_init_factorial.json`, `dynamic_init_fast_selection.json` | All four states at each locked phase, including complete estimator divergence |
| Can accurate poses hide ambiguous g/ba allocations? | `coupled_state_init.json` | Both signs of paired perturbations and gravity-only controls; no independent ba truth |
| Does dimension reduction provide useful speedup? | `runtime_benchmark.json` | Per-frame core timing and map workload; component effect is not stable end-to-end acceleration |
| Is the conclusion sensitive to IMU weighting or proxy freezing? | `summary.json` | True-dimension weight/init scans and separately named legacy proxy runs |

All report paths above are relative to `report/`. Fig. 2's retained single scan
is qualitative only; its original intensity audit is `design_pointcloud.json`.

## Outcomes that must remain visible

Hall05's failed FixG/5° dropout repeat is retained as a reset outcome with no
admitted precision value. Two TUHH excessive-arc outputs are complete finite
trajectories on shared usable GT: retain their accuracy with warnings. Dynamic
start fixed-ba divergences remain failures and are excluded from ordinary
percentage summaries. Technical exclusions (interrupted execution, timestamp
mismatch, stale instrumentation) have separate audit records. None of these
categories should be silently replaced by a successful repeat.

No unconditional claim that all gravity-assisted methods fail follows from
these experiments. The counterexample targets the inference that improving
same-IMU direction consistency necessarily improves vertical trajectory error.
