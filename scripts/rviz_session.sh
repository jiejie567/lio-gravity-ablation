#!/usr/bin/env bash
# RViz 可视化会话(浏览器观看,不用于正式计时)
# 用法:
#   ./scripts/rviz_session.sh start                     # 起桌面,浏览器打开 http://localhost:6080/vnc.html
#   ./scripts/rviz_session.sh run <A|B|C|D> <bag路径> [base_config]
#                                                       # 在桌面里跑一次实验(带 RViz 画面)
#   ./scripts/rviz_session.sh stop                      # 关闭并删除容器
set -euo pipefail
export PATH="$HOME/.orbstack/bin:$PATH"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NAME=fastlio_rviz

case "${1:-}" in
start)
    docker rm -f $NAME >/dev/null 2>&1 || true
    docker run -d --name $NAME -p 6080:6080 -e DISABLE_ROS1_EOL_WARNINGS=1 \
        -v "$ROOT":/work --shm-size=2g fastlio_rviz:noetic >/dev/null
    echo "等待桌面就绪..."
    for i in $(seq 1 30); do
        curl -sf -o /dev/null http://localhost:6080/vnc.html && break
        sleep 1
    done
    echo "浏览器打开: http://localhost:6080/vnc.html?autoconnect=true&resize=scale"
    ;;
run)
    METHOD=${2:?run 需要方法 A|B|C|D}
    BAG=${3:?run 需要 bag 路径(相对项目根)}
    BASE_CONFIG=${4:-config/avia.yaml}
    case $METHOD in
      A) FG=false; FB=false;; B) FG=true; FB=false;;
      C) FG=true;  FB=true;;  D) FG=false; FB=true;;
      *) echo "method 必须是 A|B|C|D"; exit 1;;
    esac
    docker exec $NAME bash -c "cat > /tmp/exp_viz.yaml <<EOF
experiment:
  freeze_gravity: $FG
  freeze_ba: $FB
  grav_init_error_deg: 0.0
  state_log_path: /tmp/state_log_viz.csv
pcd_save:
  pcd_save_en: false
EOF"
    echo "RViz 画面在浏览器 http://localhost:6080/vnc.html 里,Ctrl-C 结束"
    docker exec $NAME bash -c "
        source /opt/ros/noetic/setup.bash && source /work/catkin_ws/devel/setup.bash
        case '$BASE_CONFIG' in /*) BC='$BASE_CONFIG';; *) BC=/work/catkin_ws/src/FAST_LIO/$BASE_CONFIG;; esac
        roslaunch fast_lio mapping_exp.launch base_config:=\$BC exp_config:=/tmp/exp_viz.yaml rviz:=true &
        LP=\$!
        for i in \$(seq 1 60); do rosnode list 2>/dev/null | grep -q laserMapping && break; sleep 1; done
        sleep 3
        rosbag play --quiet /work/$BAG
        sleep 3
        rosnode kill /laserMapping >/dev/null 2>&1 || true
        kill \$LP 2>/dev/null || true"
    ;;
stop)
    docker rm -f $NAME >/dev/null 2>&1 && echo "已停止" || echo "没有在运行"
    ;;
*)
    echo "用法: $0 start | run <A|B|C|D> <bag> [base_config] | stop"; exit 1;;
esac
