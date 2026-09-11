#!/usr/bin/env bash
# 相对 v4 的唯一变化: 在 IMU 权重 ×0.1 档上加 B 与 D,把"冻结代价"拆成重力项与 ba 项。
#
# 为什么必须拆: ×0.1 档实测 C 比 A 差 42.7%,但 C 同时冻了 g 和 ba,而该序列的 ba
# 到运行结束仍以自身 41% 的幅度移动。若这 42.7% 主要来自冻 ba,则"在线估计重力可省"
# 这一核心主张不受影响,论文只需补上"ba 未收敛时不要冻 ba"的边界;
# 若主要来自冻 g,则核心主张本身就是调参相关的,批评力度必须整体收窄。
#   B = 只冻 g(ba 在线)  → 隔离重力项
#   D = 只冻 ba(g 在线)  → 隔离 ba 项
cd ~/Desktop/fastlio_gravity_exp || exit 1

ATV=/work/configs/mcd_atv_os1_imuint_off01.yaml
HHS=/work/configs/mcd_hhs_os1_imuint_off01.yaml
TUNE=configs/exp_tuning.yaml

run() {
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

# ---- 0. 超加性跨序列验证: ntu_day_10 的 ×0.01 档拆成重力项与 ba 项 ----
# 该档 C/A = +36.1%,是这条序列上唯一有可分解效应的档位(×0.1 处仅 +0.5%)。
# 超加性目前只有 ntu_night_04 单序列证据,而它已写进论文,必须交叉验证。
for m in B D; do
    run $m data/mcd/ntu_day_10_os1 "${m}_imuw0p01" "$ATV" \
        -x configs/exp_tuning_imuw0p01.yaml -r 1.5 -p
done
run D data/mcd/ntu_day_10_os1 D "$ATV" -r 1.5 -p

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

# ---- 5b. 更狠的丢帧档: 每 20 s 挖 5 s(挖掉 25% 的雷达帧)----
# 1 s 档实测太温和 —— A 自己都没劣化(-3%),等于没检验"约束缺失"这一情形,
# 而那正是论文划界主张(重力增强方法在何处才值钱)所依赖的regime。
mkdir -p data/mcd/ntu_day_10_drop5x20
ln -sf ../degraded/ntu_day_10_drop5x20.bag data/mcd/ntu_day_10_drop5x20/os1.bag
for m in A C; do run $m data/mcd/ntu_day_10_drop5x20 "$m" "$ATV" -r 1.5 -p; done

# ---- 5c. 中间方案: 冻重力 + 收紧 ba 随机游走(b_acc_cov 1e-4 → 1e-6)----
# 只能验证必要条件(精度不掉、ba 有界);发散不可复现,稳定性收益无法在本批证明。
for seq in ntu_day_10_os1 tuhh_day_04_os1; do
    run B data/mcd/$seq B_tightba "$([ $seq = tuhh_day_04_os1 ] && echo $HHS || echo $ATV)" \
        -x configs/exp_tuning_tightba.yaml -r 1.5 -p
done

# ---- 6. 重复批(价值最低,放最后)----
for r in 4 5; do run B data/mcd/tuhh_day_04_os1 "B_r$r" "$HHS" -r 2 -p; done
run C data/mcd/tuhh_day_04_os1 C_r5 "$HHS" -r 2 -p
for r in 1 2 3 4 5; do
    for m in A B C; do run $m data/mcd/ntu_day_10_os1 "${m}_r$r" "$ATV" -r 1.5 -p; done
done

echo BATCH_V8_DONE
