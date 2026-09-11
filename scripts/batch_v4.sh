#!/usr/bin/env bash
# 剩余实验(可重入)。相对 v3 的唯一变化: 新增 IMU 权重消融并把它排在重复批之前。
#
# 为什么加这个: 现有 "A≈C" 可能被质疑成"FAST-LIO 给 IMU 的权重本来就低,
# 重力压根没机会发挥作用"。方法 O 只探了权重更低的一侧(过程噪声 ×10³~10⁴)。
# 这里把过程噪声按 ×0.01 / ×0.1 / ×10 扫一遍,在每档上比 A 与 C:
#   若两者在高 IMU 权重下分开 → 等价性是调参相关的,必须在论文中划出边界;
#   若始终不分开 → 结论强得多,直接堵掉这条审稿意见。
# 序列选 ntu_night_04(重力游走最大 4.0°,且是 C 唯一未被解释的反例)。
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

# ---- 0. IMU 权重消融(新增,最高优先级)----
for w in 0p01 0p1 10; do
    for m in A C; do
        run $m data/mcd/ntu_night_04_os1 "${m}_imuw$w" "$ATV" \
            -x "configs/exp_tuning_imuw$w.yaml" -r 1.5 -p
    done
done
# 第二条序列上复核(重力游走 2.95°,车载快)
for w in 0p01 10; do
    for m in A C; do
        run $m data/mcd/ntu_day_10_os1 "${m}_imuw$w" "$ATV" \
            -x "configs/exp_tuning_imuw$w.yaml" -r 1.5 -p
    done
done

# ---- 1. 时间偏移剂量-反应 ----
for o in -0.05 -0.08 -0.12 -0.15; do
    run A data/mcd/ntu_day_10_os1 "A_off$o" "/work/configs/mcd_atv_os1_off$o.yaml" -r 1.5 -p
done

# ---- 2. 受控退化 × A/C(+ 丢帧档加跑 B)----
for v in range20 fov60 drop1x20; do
    mkdir -p "data/mcd/ntu_day_10_$v"
    ln -sf "../degraded/ntu_day_10_$v.bag" "data/mcd/ntu_day_10_$v/os1.bag"
    for m in A C; do run $m "data/mcd/ntu_day_10_$v" "$m" "$ATV" -r 1.5 -p; done
done
run B data/mcd/ntu_day_10_drop1x20 B "$ATV" -r 1.5 -p

# ---- 3. 方法 E:重力先验权重扫描 ----
for g in 0.01 0.1 0.5 0.9; do
    run A data/mcd/ntu_day_10_os1 "E_g$g" "$ATV" -G "$g" -r 1.5 -p
done

# ---- 4. O 的 bg 冻结对照 ----
run C data/mcd/tuhh_day_04_os1 O_bgfrozen "$HHS" -x configs/exp_tuning_obsonly.yaml -g -r 2 -p
run C data/mcd/ntu_day_02_os1  O_bgfrozen "$ATV" -x configs/exp_tuning_obsonly.yaml -g -r 1.5 -p

# ---- 5. 滑窗地图补齐 ----
run C data/mcd/ntu_day_01_os1 C_w100 "$ATV" -w 100 -r 1.5 -p

# ---- 6. 重复批(价值最低,放最后)----
for r in 4 5; do run B data/mcd/tuhh_day_04_os1 "B_r$r" "$HHS" -r 2 -p; done
run C data/mcd/tuhh_day_04_os1 C_r5 "$HHS" -r 2 -p
for r in 1 2 3 4 5; do
    for m in A B C; do run $m data/mcd/ntu_day_10_os1 "${m}_r$r" "$ATV" -r 1.5 -p; done
done

echo BATCH_V4_DONE
