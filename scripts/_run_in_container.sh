#!/usr/bin/env bash
# (容器内部使用,由 run_experiment.sh 调用)
# 参数: <bag绝对路径> <base_config> <run_dir> [rate] [launch] [start_sec] [duration_sec]
set -euo pipefail
BAG=$1; BASE_CONFIG=$2; RUN_DIR=$3; RATE=${4:-1}; LAUNCH=${5:-mapping_exp}; START_SEC=${6:-0}; DURATION_SEC=${7:-0}

source /opt/ros/noetic/setup.bash
source /work/catkin_ws/devel/setup.bash

PKG_DIR=/work/catkin_ws/src/FAST_LIO
case "$BASE_CONFIG" in /*) ;; *) BASE_CONFIG="$PKG_DIR/$BASE_CONFIG";; esac
[ -f "$BASE_CONFIG" ] || { echo "base_config 不存在: $BASE_CONFIG"; exit 1; }
# BAG 可以是单个 .bag,也可以是包含多个 .bag 的目录(按时间戳同步同播,如 MCD 的 lidar+imu 拆分包)
if [ -d "$BAG" ]; then
    BAGS=$(ls "$BAG"/*.bag 2>/dev/null || true)
    [ -n "$BAGS" ] || { echo "目录中没有 bag: $BAG"; exit 1; }
else
    [ -f "$BAG" ] || { echo "bag 不存在: $BAG"; exit 1; }
    BAGS="$BAG"
fi

mkdir -p "$PKG_DIR/PCD"
rm -f "$PKG_DIR/PCD/scans.pcd"

roslaunch fast_lio ${LAUNCH}.launch \
    base_config:="$BASE_CONFIG" \
    exp_config:="$RUN_DIR/exp_params.yaml" \
    rviz:=false &
LAUNCH_PID=$!

for i in $(seq 1 60); do
    rosnode list 2>/dev/null | grep -q /laserMapping && break
    sleep 1
done
rosnode list 2>/dev/null | grep -q /laserMapping || { echo "laserMapping 启动失败"; kill $LAUNCH_PID 2>/dev/null; exit 1; }
sleep 2

# -d 3: 广播话题后等 3 s 再开始发(默认 0.2 s)。订阅方偶尔来不及接上会丢掉第一帧,
# 而丢首帧会移动初始化与对齐窗(实测 RMSE_z 变动可达 2.5%),且帧数与同序列其他
# 运行不一致 —— 零容差闸门会直接作废该次运行。实测发生率约 6%(2/32)。
PLAY_ARGS=(--quiet -d 3 -r "$RATE")
[ "$START_SEC" = "0" ] || PLAY_ARGS+=(-s "$START_SEC")
[ "$DURATION_SEC" = "0" ] || PLAY_ARGS+=(-u "$DURATION_SEC")
rosbag play "${PLAY_ARGS[@]}" $BAGS

# 等 FAST-LIO 把积压的缓冲全部处理完: state_log 连续 3 次(每 5s)不增长才收尾。
# 处理速度低于实时是允许的(消息全部入队不丢),但必须等它追完,保证各方法处理同样的数据。
LOG="$RUN_DIR/state_log.csv"
stable=0; last=-1
for i in $(seq 1 360); do
    cur=$(wc -c < "$LOG" 2>/dev/null || echo 0)
    if [ "$cur" = "$last" ]; then stable=$((stable+1)); else stable=0; fi
    [ $stable -ge 12 ] && break   # 连续 60 s 无进展即认定结束(中位单帧 100 ms;误切由帧数闸门兜底)
    last=$cur
    sleep 5
done
rosnode kill /laserMapping >/dev/null 2>&1 || true
# wait 加超时兜底: 节点若不响应 shutdown(实测系统性发生),30s 后强杀
for i in $(seq 1 6); do kill -0 $LAUNCH_PID 2>/dev/null || break; sleep 5; done
if kill -0 $LAUNCH_PID 2>/dev/null; then
    echo "节点未响应 shutdown,强制终止"
    pkill -9 -f fastlio_mapping 2>/dev/null || true
    kill -9 $LAUNCH_PID 2>/dev/null || true
fi
wait $LAUNCH_PID 2>/dev/null || true

[ -f "$PKG_DIR/PCD/scans.pcd" ] && mv "$PKG_DIR/PCD/scans.pcd" "$RUN_DIR/map.pcd"
if ls "$PKG_DIR"/PCD/scans_*.pcd >/dev/null 2>&1; then
    mkdir -p "$RUN_DIR/pcd" && mv "$PKG_DIR"/PCD/scans_*.pcd "$RUN_DIR/pcd/"
fi
if [ -f "$RUN_DIR/state_log.csv" ]; then
    echo "state_log 行数: $(wc -l < "$RUN_DIR/state_log.csv")"
else
    echo "警告: 未生成 state_log.csv"; exit 1
fi
