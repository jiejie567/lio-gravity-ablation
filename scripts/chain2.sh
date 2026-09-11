#!/usr/bin/env bash
# 今晚的串行队列(第二版)。run_experiment.sh 已加互斥锁,并发启动会被拒绝,
# 但队列本身也必须是串行的 —— 上一版翻车正是因为压缩上下文前排的定时队列成了
# 孤儿进程(PPID=1)与新队列同时开跑。这里所有批次一律前台顺序执行。
cd ~/Desktop/fastlio_gravity_exp || exit 1

guard() {   # 任何时刻只允许一个队列
    if [ -e .chain.lock ] && kill -0 "$(cat .chain.lock)" 2>/dev/null; then
        echo "已有队列在跑 (pid $(cat .chain.lock)),退出"; exit 1
    fi
    echo $$ > .chain.lock
    trap 'rm -f .chain.lock' EXIT INT TERM
}
guard

echo "[链2] === 1/4 补跑被并发污染的 fov60 两格 ==="
bash scripts/batch_red_degrade.sh          # 可重入: 已完成的自动跳过

echo "[链2] === 2/4 退化加密 (20 次) ==="
bash scripts/batch_deg2.sh

echo "[链2] === 3/4 RED18OBS (12 序列) ==="
bash scripts/batch_red18obs.sh

# ntu_day_02/A 是主表基线, 08-06 用旧 commit 跑的, 且与另一次运行重叠 61 s。
# 不覆盖原运行 —— 而是用今天的二进制重跑一份对照: 若与原运行逐字节相同,
# 则同时证明"那次重叠无影响"与"新旧二进制对方法 A 行为一致"
# (ntu_day_10 上已验过: A(08-06) 与 A_r2/r3/r4(08-09) sha1 相同)。
echo "[链2] === 4/4 ntu_day_02/A 复核 ==="
if [ ! -f results/ntu_day_02_os1/A_recheck/state_log.csv ]; then
    ./scripts/run_experiment.sh A data/mcd/ntu_day_02_os1 \
        -c /work/configs/mcd_atv_os1_imuint_off01.yaml -x configs/exp_tuning.yaml \
        -n A_recheck -r 1.5 -p
fi

echo CHAIN2_DONE "$(date '+%Y-%m-%d %H:%M:%S')"
