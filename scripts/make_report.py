#!/usr/bin/env python3
"""汇总所有序列的分析结果,生成最终 report/report.md。

用法: make_report.py [--results /work/results] [--out /work/report]
把每个 results/<seq>/analysis/ 的 section.md、metrics.json、map_metrics.json
和 plots 合并;结论段自动比较 method A vs B 的 RMSE_z。
"""
import argparse, glob, json, os, shutil


METHOD_TABLE = """\
| 方法 | gravity | ba | 说明 |
|---|---|---|---|
| A | online | online | 原版 FAST-LIO2 (baseline) |
| B | fixed | online | 冻结重力方向 (待验证方案) |
| C | fixed | fixed | 消融: 同时冻结 ba |
| D | online | fixed | 消融: 仅冻结 ba |
"""

CHANGES = """\
## 代码修改

改动位于 `catkin_ws/src/FAST_LIO` 分支 `frozen-gravity-exp`,完整 diff 见 [code_changes.patch](code_changes.patch)。

1. `include/IKFoM_toolkit/esekfom/esekfom.hpp`
   - 新增公开成员 `frozen_dx_blocks`(误差状态块列表)。
   - `update_iterated_dyn_share_modified()` 中,在 `x_.boxplus(dx_)` 之前把列出的
     误差状态块清零,即任务书要求的 `dx.gravity.setZero()`。状态维度不变,
     过程模型本身不改变 gravity(过程噪声无重力项),因此清零后 gravity 全程恒定。
2. `src/laserMapping.cpp`
   - 新增 ros 参数 `experiment/freeze_gravity`、`experiment/freeze_ba`、
     `experiment/grav_init_error_deg`、`experiment/state_log_path`。
   - 误差状态布局 (23 DOF): pos 0-2, rot 3-5, offset_R 6-8, offset_T 9-11,
     vel 12-14, bg 15-17, **ba 18-20**, **grav 21-22 (S2)**;冻结即注册对应块。
   - IMU 初始化后的第一帧可按参数把重力方向绕水平轴旋转指定角度(初始误差注入)。
   - 每帧输出状态 CSV(t, pos, quat, vel, bg, ba, grav);冻结模式下逐帧校验
     gravity 与初始参考一致(容差 1e-10,违背即打印 ERROR)。
3. 新增 `launch/mapping_exp.launch`:headless,base 传感器配置 + 每次运行的
   实验参数 overlay。

**状态变化**:baseline 的 23 维误差状态全部参与更新;frozen 模式下 gravity
(及可选 ba)的更新增量恒为零,等效于状态从估计量退化为常量,但保留在状态中
(不改 IKFoM 维度)。
"""


def main(args):
    os.makedirs(args.out, exist_ok=True)
    parts = ["# FAST-LIO2 Frozen Gravity 实验报告", "",
             "## 假设", "",
             "> FAST-LIO2 初始化后继续在线估计重力方向,在弱激励条件下可能导致竖直方向漂移。",
             "", "## 实验设置", "", METHOD_TABLE, "",
             "各方法共用同一二进制、同一参数、同一数据,仅 `experiment/*` 开关不同。",
             "", CHANGES]

    conclusions = []
    for seq_dir in sorted(glob.glob(os.path.join(args.results, "*", "analysis"))):
        seq = os.path.basename(os.path.dirname(seq_dir))
        sec = os.path.join(seq_dir, "section.md")
        if not os.path.exists(sec):
            continue
        # 拷贝图片进 report,使 report 目录自包含
        dst_plots = os.path.join(args.out, "plots", seq)
        os.makedirs(dst_plots, exist_ok=True)
        for png in glob.glob(os.path.join(seq_dir, "plots", "*.png")):
            shutil.copy(png, dst_plots)
        body = open(sec).read().replace("plots/", f"plots/{seq}/")
        parts += ["", body]

        mm = os.path.join(seq_dir, "map_metrics.json")
        if os.path.exists(mm):
            m = json.load(open(mm))
            parts += ["", f"地图竖直一致性 ({seq}):", ""]
            parts.append("| method | 地面RMS厚度 [cm] | 地面倾角 [deg] | 内点数 |")
            parts.append("|---|---|---|---|")
            for r, v in m.items():
                parts.append(f"| {r} | {v['ground_rms_thickness_m']*100:.1f} | "
                             f"{v['ground_tilt_deg']:.2f} | {v['ground_inliers']} |")

        mj = os.path.join(seq_dir, "metrics.json")
        if os.path.exists(mj):
            met = json.load(open(mj))["runs"]
            if "A" in met and "B" in met and "rmse_z_m" in met["A"]:
                a, b = met["A"]["rmse_z_m"], met["B"]["rmse_z_m"]
                rel = (a - b) / a * 100 if a > 0 else 0
                verdict = "支持" if rel > 10 else ("不支持" if rel < -10 else "不明显")
                conclusions.append(
                    f"- `{seq}`: RMSE_z A={a:.4f} m, B={b:.4f} m "
                    f"(B 相对 A {'降低' if rel >= 0 else '升高'} {abs(rel):.1f}%) → **{verdict}**")

    parts += ["", "## 结论:是否支持研究假设", ""]
    if conclusions:
        parts += conclusions
        parts += ["", "判据: B 的 RMSE_z 比 A 低 10% 以上记为支持;高 10% 以上记为不支持;"
                      "其余记为不明显。最终结论请结合弱激励序列与运动充分序列的对比综合判断。"]
    else:
        parts += ["(尚无带 GT 的序列结果;跑完正式数据集后重新生成本报告。)"]

    out_md = os.path.join(args.out, "report.md")
    with open(out_md, "w") as f:
        f.write("\n".join(parts) + "\n")
    print(f"报告已生成: {out_md}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="/work/results")
    ap.add_argument("--out", default="/work/report")
    main(ap.parse_args())
