#!/usr/bin/env bash
# 跑一次实验并归档结果。
# 用法: ./scripts/run_experiment.sh <A|B|C|D> <bag路径(相对项目根)> [选项]
#   -c <base_config>  FAST-LIO 传感器配置;相对 FAST_LIO 包或绝对路径 (默认 config/avia.yaml)
#   -e <deg>          初始重力方向误差注入角度 (默认 0)
#   -T <sec>          从首帧起经过 sec 后，在下一条 LiDAR 更新前锁住当前重力
#   -U <sec>          在 sec 后把同一 Online 历史切换为协方差一致的 21D FixG
#   -J <projection>   -U 的协方差投影: marginal(默认)或 conditional
#   -S <sec>          从 bag 起点偏移 sec 后开始播放 (默认 0)
#   -u <sec>          只播放 sec 秒;0 表示播放到 bag 末尾 (默认 0)
#   -q <seq_name>     覆盖结果序列目录名,用于同一 bag 的裁段实验
#   -n <run_name>     结果子目录名 (默认 <method> 或 <method>_err<deg>)
#   -p                关闭 PCD 地图保存 (默认开启)
#
# 方法定义(任务书消融表):
#   A: gravity online, ba online   (原版 baseline)
#   B: gravity fixed,  ba online   (待验证方案)
#   C: gravity fixed,  ba fixed
#   D: gravity online, ba fixed
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
METHOD=${1:?用法: run_experiment.sh <A|B|C|D> <bag> [-c cfg] [-e deg] [-n name] [-p]}
BAG=${2:?缺少 bag 路径}
shift 2

BASE_CONFIG="config/avia.yaml"; GRAV_ERR=0; GRAV_FREEZE_AFTER=-1; WARM_FIXG_AFTER=-1; WARM_FIXG_PROJECTION=marginal; START_SEC=0; DURATION_SEC=0; SEQ_OVERRIDE=""; RUN_NAME=""; PCD_EN=true; EXTRA_YAML=""; RATE=1; MAP_WIN=0; BA_INIT=""; GRAV_PRIOR=0; PCD_INTERVAL=-1; FBG=false; LAUNCH="mapping_exp"
while getopts "c:e:T:U:J:S:u:q:n:x:r:w:B:G:P:L:pg" opt; do case $opt in
  L) LAUNCH=$OPTARG;;       # mapping_exp(默认23维) | mapping_exp_red(18维真降维)
  g) FBG=true;;             # 额外冻结陀螺零偏 bg(方法O用;必须写进 experiment: 块,
                            # 平铺的 "experiment/freeze_bg:" 斜杠键 rosparam 不认,实测无效)
  B) BA_INIT=$OPTARG;;      # 初始化后注入 ba(体坐标系,"bx by bz"),配合 C 模式做冻结点对照
  G) GRAV_PRIOR=$OPTARG;;   # 方法E: 每帧重力方向先验权重(0=关)
  P) PCD_INTERVAL=$OPTARG;; # PCD 分块保存间隔帧数(默认-1=单文件;用于地图姿态-时间分析)
  c) BASE_CONFIG=$OPTARG;;
  e) GRAV_ERR=$OPTARG;;
  T) GRAV_FREEZE_AFTER=$OPTARG;; # Online 预热后锁住当时的重力；机制对照，不是真降维
  U) WARM_FIXG_AFTER=$OPTARG;;   # 同一历史下切换到精确 21D 活动子空间
  J) WARM_FIXG_PROJECTION=$OPTARG;; # marginal | conditional
  S) START_SEC=$OPTARG;;     # rosbag play 起播偏移,相对 bag 起点
  u) DURATION_SEC=$OPTARG;;  # rosbag play 时长;0=直到 bag 末尾
  q) SEQ_OVERRIDE=$OPTARG;;  # 独立结果组,避免裁段运行污染全长序列的帧数闸门
  n) RUN_NAME=$OPTARG;;
  x) EXTRA_YAML=$OPTARG;;   # 额外调参 overlay(相对项目根),原样并入 exp_params.yaml
  r) RATE=$OPTARG;;         # rosbag 回放倍速;缓冲不丢帧+drain收尾,结果与1x等价(注意内存)
  w) MAP_WIN=$OPTARG;;      # 地图滑动窗口帧数(0=原版无限地图)
  p) PCD_EN=false;;
  *) exit 1;;
esac; done

case $METHOD in
  A) FG=false; FB=false;;
  B) FG=true;  FB=false;;
  C) FG=true;  FB=true;;
  D) FG=false; FB=true;;
  *) echo "method 必须是 A|B|C|D"; exit 1;;
esac

if [ "$GRAV_FREEZE_AFTER" != "-1" ]; then
  [ "$METHOD" = "A" ] || { echo "-T 只允许用于方法 A；静态冻结方法不能再次延迟冻结"; exit 1; }
  [ "$LAUNCH" = "mapping_exp" ] || { echo "-T 只支持 23D mapping_exp 机制对照"; exit 1; }
fi
if [ "$WARM_FIXG_AFTER" != "-1" ]; then
  [ "$METHOD" = "A" ] || { echo "-U 只允许从 Online 方法 A 热切换"; exit 1; }
  [ "$LAUNCH" = "mapping_exp" ] || { echo "-U 只支持 23D mapping_exp 的运行时活动子空间"; exit 1; }
  [ "$GRAV_FREEZE_AFTER" = "-1" ] || { echo "-U 不能与 -T 同时使用"; exit 1; }
  case "$WARM_FIXG_PROJECTION" in marginal|conditional) ;; *) echo "-J 必须是 marginal|conditional"; exit 1;; esac
fi

SEQ=$(basename "$BAG" .bag)
[ -n "$SEQ_OVERRIDE" ] && SEQ=$SEQ_OVERRIDE
if [ -z "$RUN_NAME" ]; then
  RUN_NAME=$METHOD
  [ "$GRAV_ERR" != "0" ] && RUN_NAME="${METHOD}_err${GRAV_ERR}"
fi
RUN_DIR_REL="results/$SEQ/$RUN_NAME"
RUN_DIR="$ROOT/$RUN_DIR_REL"
mkdir -p "$RUN_DIR"

cat > "$RUN_DIR/exp_params.yaml" <<EOF
experiment:
  freeze_gravity: $FG
  freeze_gravity_after_sec: $GRAV_FREEZE_AFTER
  freeze_event_log_path: /work/$RUN_DIR_REL/freeze_event.csv
  warm_fixg_after_sec: $WARM_FIXG_AFTER
  warm_fixg_projection: $WARM_FIXG_PROJECTION
  warm_fixg_event_log_path: /work/$RUN_DIR_REL/warm_fixg_event.csv
  freeze_ba: $FB
  grav_init_error_deg: $GRAV_ERR
  map_window_frames: $MAP_WIN
  freeze_bg: $FBG
  grav_prior_weight: $GRAV_PRIOR$([ -n "$BA_INIT" ] && echo "
  ba_init: [$(echo $BA_INIT | tr ' ' ',')]")
  state_log_path: /work/$RUN_DIR_REL/state_log.csv
pcd_save:
  pcd_save_en: $PCD_EN
  interval: $PCD_INTERVAL
EOF
if [ -n "$EXTRA_YAML" ]; then
  [ -f "$ROOT/$EXTRA_YAML" ] || { echo "额外 yaml 不存在: $EXTRA_YAML"; exit 1; }
  cat "$ROOT/$EXTRA_YAML" >> "$RUN_DIR/exp_params.yaml"
fi

# 互斥锁: 两次 FAST-LIO 同时跑会改变 OMP 线程调度, 实测把 RMSE_z 挪 1.1%、ATE 挪 3.8%
# —— 与本文要测的效应同量级。宁可排队也不能并发, 所以这里直接拒绝启动。
LOCK="$ROOT/.run.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  OWNER=$(cat "$LOCK/pid" 2>/dev/null || echo "?")
  if kill -0 "$OWNER" 2>/dev/null; then
    echo "拒绝启动: 已有运行在进行中 (pid $OWNER, $(cat "$LOCK/what" 2>/dev/null))" >&2
    echo "并发会污染结果, 请等它结束。" >&2
    exit 3
  fi
  echo "发现陈旧锁(pid $OWNER 已不存在), 接管" >&2
  rm -rf "$LOCK"; mkdir "$LOCK"
fi
echo $$ > "$LOCK/pid"; echo "$RUN_DIR_REL" > "$LOCK/what"
trap 'rm -rf "$LOCK"' EXIT INT TERM

{ echo "method: $METHOD (freeze_gravity=$FG freeze_ba=$FB freeze_bg=$FBG grav_err=$GRAV_ERR freeze_after_sec=$GRAV_FREEZE_AFTER warm_fixg_after_sec=$WARM_FIXG_AFTER warm_fixg_projection=$WARM_FIXG_PROJECTION)"
  echo "bag: $BAG"
  echo "base_config: $BASE_CONFIG"
  echo "date: $(date +%Y-%m-%dT%H:%M:%S)"
  echo "launch: $LAUNCH"
  echo "play_rate: $RATE"
  echo "play_start_sec: $START_SEC"
  echo "play_duration_sec: $DURATION_SEC"
  echo "fastlio_commit: $(git -C "$ROOT/catkin_ws/src/FAST_LIO" rev-parse HEAD)"
  # 注意: 上面是源码 HEAD,不代表二进制。下面记录实际执行文件的时间戳与哈希,
  # 否则"改了代码但没重编"这类错误无法从产物中发现(本项目 freeze_bg 就栽过)。
  # 指纹必须跟随 -L 实际启动的节点,否则降维运行会记录主二进制的哈希
  BIN="$ROOT/catkin_ws/devel/lib/fast_lio/$(sed -n 's/.*pkg="fast_lio"[[:space:]]*type="\([a-z_0-9]*\)".*/\1/p' \
        "$ROOT/catkin_ws/src/FAST_LIO/launch/${LAUNCH:-mapping_exp}.launch" | head -1)"
  [ -f "$BIN" ] && echo "fastlio_binary_mtime: $(date -r "$BIN" +%Y-%m-%dT%H:%M:%S)"
  [ -f "$BIN" ] && echo "fastlio_binary_sha1: $(shasum "$BIN" | cut -c1-12)"
} > "$RUN_DIR/run_meta.txt"

"$ROOT/docker/run.sh" "/work/scripts/_run_in_container.sh /work/$BAG $BASE_CONFIG /work/$RUN_DIR_REL $RATE $LAUNCH $START_SEC $DURATION_SEC" 2>&1 | tee "$RUN_DIR/console.log"
echo "== 完成: $RUN_DIR_REL"
