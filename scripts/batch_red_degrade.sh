#!/usr/bin/env bash
# 退化档的真降维实验: 已有的退化结论(限距/窄视场/丢帧)全部来自 dx 清零代理,
# 而代理在部分格子上偏差可达 7%。这里用真降维重跑,回答"轻度退化下是否仍等价、
# 约束缺失时是不是只有'两者都去'才崩"。
cd ~/Desktop/fastlio_gravity_exp || exit 1
ATV=/work/configs/mcd_atv_os1_imuint_off01.yaml
run() {
    local bag=$1 name=$2 launch=$3
    local seq; seq=$(basename "$bag")
    [ -f "results/$seq/$name/state_log.csv" ] && { echo "== 跳过: $seq/$name"; return 0; }
    echo "== 开始: $seq/$name  $(date '+%H:%M:%S')"
    ./scripts/run_experiment.sh A "$bag" -c "$ATV" -x configs/exp_tuning.yaml \
        -n "$name" -L "$launch" -r 1.5 -p \
        && echo "== 完成: $seq/$name  $(date '+%H:%M:%S')" || echo "== 失败: $seq/$name"
}
for v in range20 fov60 drop1x20 drop5x20; do
    run "data/mcd/ntu_day_10_$v" RED21 mapping_exp_redg    # 只去重力
    run "data/mcd/ntu_day_10_$v" RED18 mapping_exp_red     # 两者都去
done
echo RED_DEGRADE_DONE
