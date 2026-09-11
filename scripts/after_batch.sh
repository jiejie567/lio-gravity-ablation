#!/usr/bin/env bash
# 批次跑完后的收尾: 重算指标 -> 验证降维变体 -> 重建论文表格 -> 立哨兵文件。
# 关机由 scripts/shutdown_watcher.sh(需 sudo 启动)看到哨兵后执行,
# 两者分开是为了不让分析步骤以 root 身份产出 root 所有的文件。
cd ~/Desktop/fastlio_gravity_exp || exit 1
SENTINEL=/tmp/fastlio_ready_to_shutdown
STATUS=report/LAST_RUN_STATUS.txt
rm -f "$SENTINEL"

echo "[收尾] 等待 batch_deg3.sh 结束 ..."
while pgrep -f 'batch_deg3.sh' > /dev/null; do sleep 30; done
# 容器可能比脚本晚半拍退出
while [ "$(docker ps -q | wc -l)" -gt 0 ]; do sleep 10; done
echo "[收尾] 批次结束 $(date '+%F %T')"

{
  echo "生成于 $(date '+%F %T')"
  echo
  echo "== 批次结果 =="
  grep -E '^== (完成|失败)' /tmp/deg3.log | grep -v '^== 完成: results/' || true
  echo
  echo "== 指标重算 =="
} > "$STATUS"

.venv/bin/python scripts/collect_metrics.py >> "$STATUS" 2>&1
echo >> "$STATUS"; echo "== 降维变体验证 ==" >> "$STATUS"
VALID=0
for SUFFIX in '' _r1 _r2; do
  .venv/bin/python scripts/validate_reduced.py \
    ntu_day_10_drop2x20 ntu_day_10_drop3x20 --suffix "$SUFFIX" \
    >> "$STATUS" 2>&1 || VALID=1
done
echo >> "$STATUS"; echo "验证退出码: $VALID (0=全通过)" >> "$STATUS"

echo >> "$STATUS"; echo "== 论文表格 ==" >> "$STATUS"
.venv/bin/python scripts/make_tables.py >> "$STATUS" 2>&1 || echo "make_tables 失败" >> "$STATUS"

echo "[收尾] 完成,结果见 $STATUS"
touch "$SENTINEL"
