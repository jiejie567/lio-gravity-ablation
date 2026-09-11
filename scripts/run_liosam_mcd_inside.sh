#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 8 && $# -ne 10 ]]; then
    echo "usage: $0 <imu-node> <lidar-bag> <imu-bag> <output-dir> <setup> <start-s> <duration-s> <rate> [gravity-direction-sigma gravity-direction-log]" >&2
    exit 2
fi

IMU_NODE=$1
LIDAR_BAG=$2
IMU_BAG=$3
OUTPUT_DIR=$4
SETUP=$5
START_S=$6
DURATION_S=$7
RATE=$8
GRAVITY_DIRECTION_SIGMA=${9:--1.0}
GRAVITY_DIRECTION_LOG=${10:-}

source /opt/ros/noetic/setup.bash
source /work/liosam_ws/devel/setup.bash

mkdir -p "$OUTPUT_DIR"
ROSCORE_PID=""
LAUNCH_PID=""
ODOM_PID=""

cleanup()
{
    set +e
    if [[ -n "$ODOM_PID" ]]; then kill -INT "$ODOM_PID" 2>/dev/null; fi
    if [[ -n "$LAUNCH_PID" ]]; then kill -INT "$LAUNCH_PID" 2>/dev/null; fi
    if [[ -n "$ROSCORE_PID" ]]; then kill -INT "$ROSCORE_PID" 2>/dev/null; fi
    wait 2>/dev/null
}
trap cleanup EXIT INT TERM

roscore >"$OUTPUT_DIR/roscore.log" 2>&1 &
ROSCORE_PID=$!
for _ in $(seq 1 50); do
    if rosparam list >/dev/null 2>&1; then break; fi
    sleep 0.1
done
rosparam list >/dev/null
rosparam set use_sim_time true

roslaunch lio_sam run_mcd_ablation.launch \
    imu_node:="$IMU_NODE" \
    state_log:="$OUTPUT_DIR/state_log.csv" \
    setup:="$SETUP" \
    gravity_direction_sigma:="$GRAVITY_DIRECTION_SIGMA" \
    gravity_direction_log:="$GRAVITY_DIRECTION_LOG" \
    >"$OUTPUT_DIR/launch.log" 2>&1 &
LAUNCH_PID=$!
sleep 5
kill -0 "$LAUNCH_PID"

rostopic echo -p /lio_sam/mapping/odometry \
    >"$OUTPUT_DIR/odometry.csv" 2>"$OUTPUT_DIR/odometry_stderr.log" &
ODOM_PID=$!

rosbag play --clock -d 3 -s "$START_S" -u "$DURATION_S" -r "$RATE" \
    "$LIDAR_BAG" "$IMU_BAG" >"$OUTPUT_DIR/rosbag.log" 2>&1

last_size=-1
stable_seconds=0
for _ in $(seq 1 600); do
    current_size=$(stat -c %s "$OUTPUT_DIR/odometry.csv")
    if [[ "$current_size" = "$last_size" ]]; then
        stable_seconds=$((stable_seconds + 1))
    else
        stable_seconds=0
        last_size=$current_size
    fi
    if (( stable_seconds >= 10 )); then
        break
    fi
    sleep 1
done
if (( stable_seconds < 10 )); then
    echo "map queue did not drain within 600 s" >&2
    exit 4
fi
kill -0 "$LAUNCH_PID"
