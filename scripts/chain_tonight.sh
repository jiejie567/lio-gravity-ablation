#!/usr/bin/env bash
# 今晚的串行队列。等在跑的退化批次自行结束后再动任何脚本文件 ——
# bash 是按文件偏移边读边执行的,改动正在执行的脚本会损坏在跑的运行(本项目已损坏过两次)。
cd ~/Desktop/fastlio_gravity_exp || exit 1

echo "[链] 等待 batch_red_degrade.sh 结束 ..."
while pgrep -f 'batch_red_degrade.sh' > /dev/null; do sleep 30; done
echo "[链] 前序批次已结束 $(date '+%H:%M:%S')"

# 现在没有任何 shell 在执行 run_experiment.sh,可以安全修补指纹逻辑:
# 原实现无论 -L 选了哪个 launch,都记录主二进制 fastlio_mapping 的 sha1,
# 三个降维运行因此记录了同一个与自己无关的哈希 —— 闸门形同虚设。
.venv/bin/python - <<'PY'
from pathlib import Path

# (1) 收尾判据: 原来要"连续 5 分钟帧数不涨"才认定处理结束,而实测中位单帧 100 ms、
# 处理速度基本跟得上实时 —— 这 5 分钟纯属空等,占每次运行墙钟的 45%。
# 收到 60 s。若某次真的停顿超过 60 s 而被提前切断,帧数会少于同序列其他运行,
# collect_metrics.py 的帧数一致性闸门会把它标成 unusable,不会静默污染结果。
q = Path('scripts/_run_in_container.sh'); t = q.read_text()
old_wait = '    [ $stable -ge 60 ] && break   # 连续 5 分钟无进展才认定处理结束(大地图时单帧可能很慢)'
new_wait = '    [ $stable -ge 12 ] && break   # 连续 60 s 无进展即认定结束(中位单帧 100 ms;误切由帧数闸门兜底)'
if old_wait in t:
    q.write_text(t.replace(old_wait, new_wait)); print('[链] 收尾判据 300s -> 60s 已生效')
else:
    print('[链] 收尾判据无需修补')

# (2) 二进制指纹: 原实现无论 -L 选了哪个 launch,都记录主二进制 fastlio_mapping 的
# sha1,三个降维运行因此记录了同一个与自己无关的哈希 —— 闸门形同虚设。
p = Path('scripts/run_experiment.sh'); s = p.read_text()
old = '  BIN="$ROOT/catkin_ws/devel/lib/fast_lio/fastlio_mapping"'  # noqa

new = ('  # 指纹必须跟随 -L 实际启动的节点,否则降维运行会记录主二进制的哈希\n'
       '  BIN="$ROOT/catkin_ws/devel/lib/fast_lio/$(sed -n \'s/.*pkg="fast_lio"[[:space:]]*type="\\([a-z_0-9]*\\)".*/\\1/p\' \\\n'
       '        "$ROOT/catkin_ws/src/FAST_LIO/launch/${LAUNCH:-mapping_exp}.launch" | head -1)"')
if old in s and 'sed -n' not in s:
    p.write_text(s.replace(old, new)); print('[链] 指纹逻辑已修补')
else:
    print('[链] 指纹逻辑无需修补(已是新版或结构已变)')
PY
grep -n 'BIN=' scripts/run_experiment.sh | head -3
bash -n scripts/run_experiment.sh && echo "[链] run_experiment.sh 语法检查通过" || { echo "[链] 语法错误,中止"; exit 1; }

echo "[链] === 退化加密批次 (20 次) ==="
bash scripts/batch_deg2.sh

echo "[链] === O 的真降维版 RED18OBS (12 序列) ==="
bash scripts/batch_red18obs.sh

echo CHAIN_DONE "$(date '+%Y-%m-%d %H:%M:%S')"
