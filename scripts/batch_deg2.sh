#!/usr/bin/env bash
# 退化实验加密。已有的 4 档只能说明"1 s 丢帧没事、5 s 丢帧代价 +114%",
# 边界落在中间且无分辨率;限距/窄视场也只各有一档,无法排除"再狠一点就崩"。
#
# 本批补两件事:
#   (a) 丢帧时长的剂量曲线 1/2/3/5/10 s(每 20 s),在出效应的那一档补齐 2x2
#       析因(RED20 = 只去 ba),回答"约束缺失时到底是重力、ba、还是两者";
#   (b) 更狠的限距(10 m)与窄视场(±30°),检验"雷达变差但没缺失 ⇒ 无代价"
#       这个结论在更极端处是否仍成立。
# 全部用真降维二进制,方法一律 A(降维由 -L 选择的 launch 决定,不是运行时开关)。
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

cell() {   # 一个退化档的完整 2x2 析因
    local v=$1; shift
    for spec in "$@"; do
        case $spec in
            A)     run "data/mcd/ntu_day_10_$v" A     mapping_exp ;;
            RED21) run "data/mcd/ntu_day_10_$v" RED21 mapping_exp_redg ;;
            RED20) run "data/mcd/ntu_day_10_$v" RED20 mapping_exp_redb ;;
            RED18) run "data/mcd/ntu_day_10_$v" RED18 mapping_exp_red ;;
        esac
    done
}

# (a) 丢帧剂量曲线 —— 效应所在,优先且做满析因
cell drop2x20  A RED21 RED20 RED18
cell drop3x20  A RED21 RED20 RED18
cell drop10x20 A RED21 RED20 RED18
cell drop5x20  RED20            # 补齐已有档的析因
cell drop1x20  RED20

# (b) 更极端的"雷达变差但不缺失"
cell range10 A RED21 RED18
cell fov30   A RED21 RED18

echo DEG2_DONE
