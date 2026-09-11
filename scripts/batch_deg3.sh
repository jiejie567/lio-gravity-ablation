#!/usr/bin/env bash
# 剂量曲线的转折点加密。已测得: 丢 1 s 无事,丢 3 s 全线崩(RED21 +93%/+120%),
# 转折就落在 2–3 s 之间 —— 而论文的边界主张要建在这段上,单次运行不够。
# 另补两格被首帧竞态作废的运行(drop2x20/RED20, drop3x20/RED18)。
cd ~/Desktop/fastlio_gravity_exp || exit 1
ATV=/work/configs/mcd_atv_os1_imuint_off01.yaml

run() {
    local v=$1 name=$2 launch=$3
    local seq=ntu_day_10_$v
    [ -f "results/$seq/$name/state_log.csv" ] && { echo "== 跳过: $seq/$name"; return 0; }
    echo "== 开始: $seq/$name  $(date '+%H:%M:%S')"
    ./scripts/run_experiment.sh A "data/mcd/$seq" -c "$ATV" -x configs/exp_tuning.yaml \
        -n "$name" -L "$launch" -r 1.5 -p \
        && echo "== 完成: $seq/$name  $(date '+%H:%M:%S')" || echo "== 失败: $seq/$name"
}

# 1) 补两个被作废的格子(首帧竞态已修: rosbag play -d 3)
run drop2x20 RED20 mapping_exp_redb
run drop3x20 RED18 mapping_exp_red

# 2) 转折点重复跑 ×2, 用于判断 2 s 档的混合符号是真效应还是单次运行的偶然
for v in drop2x20 drop3x20; do
    for r in _r1 _r2; do
        run $v "A$r"     mapping_exp
        run $v "RED21$r" mapping_exp_redg
        run $v "RED20$r" mapping_exp_redb
        run $v "RED18$r" mapping_exp_red
    done
done
echo DEG3_DONE "$(date '+%H:%M:%S')"
