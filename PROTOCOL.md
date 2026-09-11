# Evaluation and data dictionary

FAST-LIO2: associate estimate timestamps with interpolated GT, transform the
estimator frame to the GT body frame using the recorded fixed calibration, and
fit a rigid SE(3) transform on a prefix spanning at least 10 seconds and 30 metres
(with the analyzer's finite-length cap). No scale is fitted. Report RMS vertical
position error and RMS Euclidean position error over the associated trajectory.
LIO-SAM: the supplied collectors use the first 10 seconds for rigid alignment,
without the FAST-LIO2 30-metre expansion. Compare variants within each system;
do not rank systems by these differently aligned absolute errors.

The paired APE diagnostic has a different purpose: fit the transform to Online
once and apply it unchanged to both history-matched branches. This keeps their
identical pre-switch history identical after alignment. Its contrast is
Warm-FixG21 APE minus Online APE, with positive values indicating larger FixG
error. These shared-alignment traces must not be substituted for independently
aligned scalar table metrics.

## Variables

| File/field | Meaning and units |
|---|---|
| FAST-LIO `state_log.csv`: `t` | ROS time, seconds |
| `px,py,pz`; `vx,vy,vz` | estimated position [m]; velocity [m/s] |
| `qx,qy,qz,qw` | unit quaternion, scalar last |
| `bgx,bgy,bgz`; `bax,bay,baz` | gyro bias [rad/s]; accelerometer bias [m/s²] |
| `gx,gy,gz` | gravity vector [m/s²], fixed norm 9.8090 for FAST-LIO |
| LIO-SAM `odometry.csv`: `%time` | ROS timestamp [ns] |
| `gravity_direction.csv` | pre/post direction residual [degrees], age [s] |
| reports: `rmse_z_m`, `ate_rmse_m` | RMS position errors [m] |
| `delta_*_pct*` | paired relative change; positive means larger error |
| JSON null / failed outcome | no admitted precision value; never zero error |

The nominal FAST-LIO population consists of 12 sequence units. The later
fingerprinted rerun repeats these same units. The prespecified symmetric log
ratio band is [1/1.05, 1.05]; the narrower 2% check is a sensitivity analysis.
Four full LIO-SAM sequences provide descriptive evidence, not a population
equivalence test. Dropout repeats and start phases remain within-trajectory
experiments. Both RMSE_z and ATE must be read together.

Exact frame counts and timestamps, fixed/online state behaviour, GT usability,
actual launch-node fingerprints, sleep records and serial execution are audited
where the original instrumentation supports them. Archived sleep checks are
historical evidence, not a check of the reviewer's current machine.
