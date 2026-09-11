# Rerunning algorithms from public recordings

The default verification commands only reanalyse recorded outputs. Algorithm
runs require the original bags, ROS1 Noetic, a C++ toolchain and Docker/Linux.
Original execution used arm64 containers; numerical identity on different
hardware or thread scheduling is not promised.

Inspect `docker/Dockerfile` and `docker/Dockerfile.liosam` before building.
The latter pins the GTSAM source revision and carries the exact compatibility
patch. `catkin_ws/src/` and `liosam_ws/src/` contain estimator and driver sources.

```sh
docker build -t fastlio_exp:noetic -f docker/Dockerfile .
docker run --rm -v "$PWD":/work fastlio_exp:noetic bash -lc \
  'source /opt/ros/noetic/setup.bash; cd /work/catkin_ws; catkin_make -j2'
docker build -t liosam_exp:noetic -f docker/Dockerfile.liosam .
docker run --rm -v "$PWD":/work liosam_exp:noetic bash -lc \
  'source /opt/ros/noetic/setup.bash; cd /work/liosam_ws; catkin_make -j2'
```

Use a fresh working copy for algorithm reruns so archived outputs are retained.
Obtain the sequences from `DATA_SOURCES.md`, placing recordings at the relative
paths recorded in `run_meta.txt` and the campaign manifests. These records carry
bag identifiers, playback rates, start offsets, launch names and settings.
Degraded bags are generated with `scripts/degrade_bag.py`; IMU and truth remain
unchanged. Read its `--help` for gap phase and duration options.

For one FAST-LIO run, the interface is:

```text
scripts/run_experiment.sh A <bag-or-directory> -c <container-config-path> \
  -x configs/exp_tuning.yaml -L <launch> -n <fresh-run-name> -p
```

Online uses `mapping_exp`; FixG `mapping_exp_redg`; FixBa `mapping_exp_redb`;
FixG+Ba `mapping_exp_red`. True-dimension runs always use method A with runtime
freeze switches disabled. Validate the first complete matched grid before
running a batch. `scripts/validate_reduced.py` implements the structural checks.

LIO-SAM entry points are `run_liosam_ablation.sh`, `run_liosam_mcd_ablation.sh`,
`run_liosam_gravity_direction.sh`, and `run_liosam_mcd_gravity_direction.sh`.
Their usage strings and the original per-run metadata define the exact args.
State names FG-BA/FG-B0/GE-BA/GE-B0 respectively represent fixed/online gravity
and online/fixed accelerometer bias. Inspect the first run with the matching
`validate_liosam_*.py` before continuing.

Never run two experiments concurrently or bypass `.run.lock` / `.chain.lock`.
Do not edit a running shell script or relocate its output. Keep the host awake,
wait for drain completion, and compare every timestamp as well as frame count.
Record actual launched executable hashes. Archived batch scripts are execution
provenance, not the reviewer quickstart: some assume original host sleep tools
or pre-existing campaign checkpoints. Reruns should use the individual runners
and fresh names. Do not silently reuse a partial `state_log.csv` as completion.
