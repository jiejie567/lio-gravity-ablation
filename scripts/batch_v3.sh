#!/usr/bin/env bash
# 剩余实验批次(可重入):已有 state_log.csv 的运行自动跳过,中断后重跑本脚本即可。
# 顺序 = 价值优先级:独有实验在前,重复跑在后 —— 中断时丢掉的是最不值钱的部分。
cd ~/Desktop/fastlio_gravity_exp || exit 1

ATV=/work/configs/mcd_atv_os1_imuint_off01.yaml
HHS=/work/configs/mcd_hhs_os1_imuint_off01.yaml
TUNE=configs/exp_tuning.yaml

run() {  # run <method> <数据目录> <运行名> <配置> [额外参数...]
    local m=$1 bag=$2 name=$3 cfg=$4; shift 4
    local seq; seq=$(basename "$bag")
    if [ -f "results/$seq/$name/state_log.csv" ]; then
        echo "== 跳过(已存在): $seq/$name"; return 0
    fi
    echo "== 开始: $seq/$name  $(date '+%H:%M:%S')"
    ./scripts/run_experiment.sh "$m" "$bag" -c "$cfg" -x "$TUNE" -n "$name" "$@" \
        && echo "== 完成: $seq/$name  $(date '+%H:%M:%S')" \
        || echo "== 失败: $seq/$name"
}

# ---- 1. 方法 O:同核观测-only(IMU 权重降 1e4),IMU 价值分解的唯一有效对照 ----
run C data/mcd/tuhh_day_04_os1 O "$HHS" -x configs/exp_tuning_obsonly.yaml -r 2 -p
run C data/mcd/ntu_day_02_os1  O_pcd "$ATV" -x configs/exp_tuning_obsonly.yaml -P 400 -r 1.5
run C data/mcd/ntu_day_10_os1  O "$ATV" -x configs/exp_tuning_obsonly.yaml -r 1.5 -p

# ---- 2. 冻结点对照:冻结在 A 收敛的 ba,而非冻结在 0(解释 +11% 与 +52.9%)----
run C data/m2dgr/hall_05_run     C_baconv /work/configs/m2dgr_vlp32.yaml -B "0.021 0.168 0.019" -r 1.5 -p
run C data/mcd/ntu_night_04_os1  C_baconv "$ATV" -B "0.299 -0.030 0.034" -r 1.5 -p

# ---- 3. 时间偏移剂量-反应(标称 -0.1,真值可用序列上重做)----
for o in -0.05 -0.08 -0.12 -0.15; do
    run A data/mcd/ntu_day_10_os1 "A_off$o" "/work/configs/mcd_atv_os1_off$o.yaml" -r 1.5 -p
done

# ---- 4. 受控退化 × A/C(+ 丢帧档加跑 B)----
for v in range20 fov60 drop1x20; do
    mkdir -p "data/mcd/ntu_day_10_$v"
    ln -sf "../degraded/ntu_day_10_$v.bag" "data/mcd/ntu_day_10_$v/os1.bag"
    for m in A C; do run $m "data/mcd/ntu_day_10_$v" "$m" "$ATV" -r 1.5 -p; done
done
run B data/mcd/ntu_day_10_drop1x20 B "$ATV" -r 1.5 -p

# ---- 5. 方法 E:重力先验权重扫描(伪需求主张的正面证据)----
for g in 0.01 0.1 0.5 0.9; do
    run A data/mcd/ntu_day_10_os1 "E_g$g" "$ATV" -G "$g" -r 1.5 -p
done

# ---- 6. 滑窗地图补齐(原 C_w100 被 CPU 抢占截断)----
run C data/mcd/ntu_day_01_os1 C_w100 "$ATV" -w 100 -r 1.5 -p

# ---- 7. 重复批(价值最低,放最后):先补齐 tuhh,再做 ntu_day_10 ----
for r in 4 5; do run B data/mcd/tuhh_day_04_os1 "B_r$r" "$HHS" -r 2 -p; done
run C data/mcd/tuhh_day_04_os1 C_r5 "$HHS" -r 2 -p
for r in 1 2 3 4 5; do
    for m in A B C; do run $m data/mcd/ntu_day_10_os1 "${m}_r$r" "$ATV" -r 1.5 -p; done
done

# ---- 8. O 的对照:真正冻住 bg(-g),确认结论对 bg 是否在线不敏感 ----
run C data/mcd/tuhh_day_04_os1 O_bgfrozen "$HHS" -x configs/exp_tuning_obsonly.yaml -g -r 2 -p
run C data/mcd/ntu_day_02_os1  O_bgfrozen "$ATV" -x configs/exp_tuning_obsonly.yaml -g -r 1.5 -p

echo BATCH_V3_DONE
