# Data access, attribution and rights

Only GT trajectories and the retained Fig. 2 point-cloud sample are redistributed
from source datasets; full LiDAR/IMU recordings must be obtained upstream.
Numerical data and time bases are preserved. Cropping, interpolation, rigid
alignment and estimator-frame conversion are documented in the collectors.

| Dataset | Official access | Included files | Source terms |
|---|---|---|---|
| MCD, Nguyen et al., CVPR 2024, pp. 22304–22313 | https://mcdviral.github.io/ | `data/mcd/*/gt/pose_inW.csv`, `report/design_pointcloud.npz` | CC BY-NC-SA 4.0; https://creativecommons.org/licenses/by-nc-sa/4.0/ |
| TIERS multi-modal LiDAR dataset | https://github.com/TIERS/multi_modal_lidar_dataset | `data/tiers/*/gt.txt` | Dataset LICENSE-DATA: CC BY 4.0; https://creativecommons.org/licenses/by/4.0/ |
| M2DGR, Yin et al., RA-L 2022 | https://github.com/SJTU-ViSYS/M2DGR | `data/m2dgr/hall_05/gt/gt.txt` | Upstream MIT notice in `notices/M2DGR-LICENSE.txt` |

The unusable TIERS road GT remains solely for inspection of the exclusion;
it is not evidence for accuracy. MCD-derived material retains its non-commercial
and share-alike conditions. This artifact does not relicense third-party data.
The original source notices and technical credits identify dataset/software
creators, not the anonymous submission authors.

FAST-LIO, LIO-SAM and Livox driver source retain their in-tree licences. Modified
files are supplied as an experimental snapshot; upstream names do not imply
upstream endorsement. Original experiment/analysis code is covered by the root MIT licence; see LICENSE_SCOPE.md for exclusions.

Public repository: https://github.com/jiejie567/rethink-lio-gravity
Versioned evidence is distributed through its Releases. No DOI is asserted.
