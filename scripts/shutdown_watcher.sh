#!/usr/bin/env bash
# 唯一职责: 等哨兵文件出现 -> 再确认没有实验在跑 -> 关机。
# 需要 sudo 启动(shutdown 需要 root)。除关机外不做任何事,不产出文件。
#
#   启动:  sudo nohup bash ~/Desktop/fastlio_gravity_exp/scripts/shutdown_watcher.sh \
#              > /tmp/shutdown_watcher.log 2>&1 &
#   取消:  touch /tmp/fastlio_cancel_shutdown     (随时,含最后 2 分钟宽限期内)
#     或:  sudo pkill -f shutdown_watcher.sh
SENTINEL=/tmp/fastlio_ready_to_shutdown
CANCEL=/tmp/fastlio_cancel_shutdown
MAX_HOURS=8

rm -f "$CANCEL"
echo "[关机守护] 启动 $(date '+%F %T'),最长等待 ${MAX_HOURS} 小时"
echo "[关机守护] 取消方式: touch $CANCEL"

deadline=$(( $(date +%s) + MAX_HOURS*3600 ))
while [ ! -f "$SENTINEL" ]; do
    [ -f "$CANCEL" ] && { echo "[关机守护] 收到取消,退出"; exit 0; }
    if [ "$(date +%s)" -gt "$deadline" ]; then
        echo "[关机守护] 超过 ${MAX_HOURS} 小时仍未收到完成信号,放弃关机并退出"; exit 1
    fi
    sleep 30
done

echo "[关机守护] 收到完成信号 $(date '+%F %T')"
# 双保险: 哨兵在但仍有容器/运行进程时不关机
for i in $(seq 1 20); do
    n=$(docker ps -q 2>/dev/null | wc -l)
    p=$(pgrep -cf 'run_experiment.sh|batch_deg' 2>/dev/null || echo 0)
    [ "$n" -eq 0 ] && [ "$p" -eq 0 ] && break
    echo "[关机守护] 仍有 容器=$n 进程=$p,再等 30s"; sleep 30
done

echo "[关机守护] 2 分钟后关机 —— 现在 touch $CANCEL 仍可取消"
for i in $(seq 1 24); do
    [ -f "$CANCEL" ] && { echo "[关机守护] 收到取消,退出"; exit 0; }
    sleep 5
done

echo "[关机守护] 关机 $(date '+%F %T')"
shutdown -h now
