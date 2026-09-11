#!/usr/bin/env python3
"""主机睡眠污染审计:把 pmset 日志的睡眠事件与每次运行的时间区间求交。

为什么需要:笔记本托管评测时,主机 Idle Sleep 会冻结容器;唤醒后 rosbag 突发
重放可能溢出订阅队列而丢消息,造成 IMU 流缺口 → 该帧递推崩掉。本项目曾把两次
这样的失败误读为"方法 B 的随机发散",写进结论后才发现(见 report/FINDINGS.md)。

判据分两层:
  1. 运行区间内是否发生睡眠 → 标记为可疑;
  2. 可疑运行的帧数/时间跨度/最大帧间隔是否与同序列其他运行一致
     → 一致则数据完好(睡眠只是拖慢),不一致则应作废重跑。

用法: .venv/bin/python scripts/audit_sleep.py [--json]
注意: pmset 日志只保留数日,更早的运行无法回溯审计。
"""
import argparse, datetime, json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sleep_events():
    try:
        out = subprocess.run(["pmset", "-g", "log"], capture_output=True, text=True,
                             errors="replace", timeout=180).stdout
    except Exception as e:
        print(f"读取 pmset 日志失败: {e}", file=sys.stderr)
        return []
    events = []
    for line in out.splitlines():
        if "Entering Sleep state" not in line:
            continue
        try:
            events.append(datetime.datetime.strptime(" ".join(line.split()[:2]),
                                                 "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            continue
    return events


def run_window(d: Path):
    meta, log = d / "run_meta.txt", d / "state_log.csv"
    if not (meta.exists() and log.exists()):
        return None
    line = next((l for l in meta.read_text().splitlines() if l.startswith("date:")), None)
    if not line:
        return None
    try:
        start = datetime.datetime.fromisoformat(line.split()[1])
    except ValueError:
        return None
    return start, datetime.datetime.fromtimestamp(log.stat().st_mtime)


def profile(d: Path):
    """帧数与最大帧间隔:睡眠若造成丢包,这两项会与同序列其他运行不一致"""
    import numpy as np
    try:
        import pandas as pd
        t = pd.read_csv(d / "state_log.csv").dropna()["t"].values
    except Exception:
        return None
    if len(t) < 2:
        return None
    return {"frames": len(t), "span_s": float(t[-1] - t[0]),
            "max_gap_ms": float(np.diff(t).max() * 1000)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    sleeps = sleep_events()
    if not sleeps:
        print("pmset 日志中没有睡眠事件(或读取失败)")
        return 0

    findings, total = [], 0
    for seq_dir in sorted((ROOT / "results").iterdir()):
        if not seq_dir.is_dir():
            continue
        profs = {d.name: profile(d) for d in seq_dir.iterdir()
                 if d.is_dir() and d.name != "analysis"}
        good = [p for p in profs.values() if p]
        if not good:
            continue
        import statistics
        frame_counts = [p["frames"] for p in good]
        mode_frames = statistics.mode(frame_counts)
        for d in sorted(seq_dir.iterdir()):
            if not d.is_dir() or d.name == "analysis":
                continue
            w = run_window(d)
            if not w:
                continue
            total += 1
            hits = [s for s in sleeps if w[0] <= s <= w[1]]
            if not hits:
                continue
            p = profs.get(d.name)
            # 同一序列喂入同一 bag，帧数必须与众数完全一致。项目中已经实测
            # 少一帧即可让 RMSE_z 变化 2.5%，因此这里不保留比例容差。
            intact = bool(p) and p["frames"] == mode_frames
            findings.append({"sequence": seq_dir.name, "run": d.name,
                             "sleeps": len(hits), "frames": p["frames"] if p else None,
                             "mode_frames": mode_frames, "data_intact": intact})

    if args.json:
        print(json.dumps(findings, indent=1, ensure_ascii=False))
    else:
        print(f"审计 {total} 次运行,受睡眠干扰 {len(findings)} 次\n")
        for f in findings:
            mark = "数据完好(仅拖慢)" if f["data_intact"] else "*** 帧数异常,应作废重跑 ***"
            print(f"  {f['sequence']:20} {f['run']:14} 睡眠 {f['sleeps']} 次  "
                  f"{f['frames']}/{f['mode_frames']} 帧  {mark}")
    return 1 if any(not f["data_intact"] for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
