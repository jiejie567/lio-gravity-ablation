#!/usr/bin/env bash
# NTU 两条 os1 bag 撞了 Google Drive 下载配额;每 30 分钟重试一次,最多 24 小时。
# 拿到合法 rosbag(#ROSBAG 头)即停;错误页(HTML)则删除等下一轮。
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
declare -a IDS=("1jDS84WvHCfM_L73EptXKp-BKPIPKoE0Z" "1p18Fa5SXbVcCa9BJb_Ed8Fk_NRcahkCF")
declare -a OUTS=("$ROOT/data/mcd/ntu_day_02/os1.bag" "$ROOT/data/mcd/ntu_day_10/os1.bag")

for i in $(seq 1 48); do
    all_done=true
    for k in 0 1; do
        out="${OUTS[$k]}"
        [ -f "$out" ] && continue
        curl -L -sS --retry 2 -m 7200 \
            "https://drive.usercontent.google.com/download?id=${IDS[$k]}&export=download&confirm=t" \
            -o "$out.part" || { all_done=false; continue; }
        if [ "$(head -c 7 "$out.part")" = "#ROSBAG" ]; then
            mv "$out.part" "$out"
            echo "[$(date +%H:%M)] OK $out $(du -h "$out" | cut -f1)"
        else
            rm -f "$out.part"
            echo "[$(date +%H:%M)] 仍被限额: $out"
            all_done=false
        fi
    done
    $all_done && { echo "全部完成"; exit 0; }
    sleep 1800
done
echo "24h 内未拿到全部文件,请手动重试"; exit 1
