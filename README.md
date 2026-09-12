# Does Online Gravity Estimation Matter?

**Revisiting a Silent Design Split in LiDAR-Inertial Odometry**

Jie Xu · Ziyi Jin · Kangjin Yu · Can Jiang · Hongjun Huang · Tongxing Jin · Hongkun Luo · Zhongpu Xia

Anyverse Dynamics

[Paper (preprint PDF)](paper/preprint.pdf) · [Video](#video) · [Reproduction archive](https://github.com/jiejie567/rethink-lio-gravity/releases/tag/v1.0.0)

Corresponding author: Zhongpu Xia. Contact: Jie Xu
([jeff_xu_0503@foxmail.com](mailto:jeff_xu_0503@foxmail.com)).

Should an LIO system keep estimating gravity after initialization? We compare
online and fixed gravity and accelerometer bias within FAST-LIO2 and LIO-SAM.
We also test an added gravity-direction factor using the same IMU as preintegration.

**Keep both gravity and accelerometer bias online by default. The tested
same-IMU direction factor is not a generic z-drift remedy.**

With continuous LiDAR updates, fixing gravity makes little difference to pose
accuracy. Keeping gravity and bias online matters more during multi-second
LiDAR outages and motion at startup. The added direction factor helps on Hall05
but hurts on TUHH with online gravity: a smaller direction residual does not
necessarily mean a smaller height error. These results do not cover independent
gravity sensors or global pose-graph priors.

## Video

https://github.com/user-attachments/assets/c3f4aaa6-e61e-4339-bcfb-015d5a785b81

Real RViz recordings with results from the experiments reported in the paper.

## Reproduce the reported results

Code and result summaries are in this repository. Trajectories, state logs,
ground truth, failure records and checksums are in
[`lio-gravity-evidence.zip`](https://github.com/jiejie567/rethink-lio-gravity/releases/tag/v1.0.0).

Download and extract that archive, then run from its root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python verify_review.py
.venv/bin/python verify_review.py --recompute --figures
```

The scripts check file integrity, recompute trajectory metrics, and regenerate
tables and figures. No ROS, Docker, GPU or raw bags are needed for these checks.

See [PROTOCOL.md](PROTOCOL.md) for evaluation and sample selection,
[EVIDENCE_MAP.md](EVIDENCE_MAP.md) for the supporting runs, and
[RUNNING.md](RUNNING.md) to rerun the estimators. Run experiments serially with
the provided run lock. The archive includes excluded runs and binary fingerprints;
use the report-defined comparisons rather than pooling all runs.

## Contents

| Location | Contents |
|---|---|
| `scripts/`, `configs/`, `docker/` | Experiment runners, validation and analysis |
| `catkin_ws/src/FAST_LIO/` | FAST-LIO2 state-removal variants |
| `liosam_ws/src/LIO-SAM/` | LIO-SAM state and direction-factor ablations |
| `report/` | Source reports and figure data |
| `paper/` | Paper, TeX sources and figures |
| `media/` | Video and preview |

Raw bags and historical binaries are not included. Dataset links and usage
terms are listed in [DATA_SOURCES.md](DATA_SOURCES.md).

## Citation and licence

Citation details are in [CITATION.cff](CITATION.cff).

Our experiment and analysis scripts use the MIT license. Third-party software,
datasets, the paper and video have separate terms; see
[LICENSE_SCOPE.md](LICENSE_SCOPE.md) and the in-tree notices.
