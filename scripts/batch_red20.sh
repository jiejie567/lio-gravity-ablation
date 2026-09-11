#!/usr/bin/env bash
# 真降维实现: 20 维,只移除 ba(策略 D 的真实现)。降维由二进制决定,故一律以方法 A 运行
# (叠加运行时冻结开关会静默冻住本该在线的状态 —— 实测踩过)。
# 目的: 主表的"冻结"一侧改用真实现,而非 dx 清零代理 —— 后者保留了被冻状态的
# 协方差块,实测对冻结策略有利约 +1.2%(见 report/FINDINGS.md 的效度检验)。
cd ~/Desktop/fastlio_gravity_exp || exit 1
ATV=/work/configs/mcd_atv_os1_imuint_off01.yaml
HHS=/work/configs/mcd_hhs_os1_imuint_off01.yaml
run() {
    local bag=$1 cfg=$2 rate=$3
    local seq; seq=$(basename "$bag")
    [ -f "results/$seq/RED20/state_log.csv" ] && { echo "== 跳过: $seq/RED20"; return 0; }
    echo "== 开始: $seq/RED20  $(date '+%H:%M:%S')"
    ./scripts/run_experiment.sh A "$bag" -c "$cfg" -x configs/exp_tuning.yaml \
        -n RED20 -L mapping_exp_redb -r "$rate" -p \
        && echo "== 完成: $seq/RED20  $(date '+%H:%M:%S')" || echo "== 失败: $seq/RED20"
}
run data/mcd/ntu_day_10_os1   "$ATV" 1.5
run data/mcd/ntu_day_02_os1   "$ATV" 1.5
run data/mcd/ntu_night_13_os1 "$ATV" 1.5
run data/mcd/ntu_day_01_os1   "$ATV" 1.5
run data/mcd/kth_day_10_os1   "$HHS" 2
run data/mcd/kth_night_05_os1 "$HHS" 2
run data/mcd/tuhh_day_02_os1  "$HHS" 2
run data/mcd/tuhh_day_04_os1  "$HHS" 2
run data/mcd/tuhh_night_09_os1 "$HHS" 2
run data/tiers/IndoorOffice1  /work/configs/tiers_mid360.yaml 2
run data/m2dgr/hall_05_run    /work/configs/m2dgr_vlp32.yaml 1.5
echo RED20_BATCH_DONE
