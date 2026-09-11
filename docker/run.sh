#!/usr/bin/env bash
# 在 fastlio_exp 容器内执行命令: ./docker/run.sh <命令...>
# 不带参数则进交互 shell。容器挂载整个项目根到 /work,用完即删(--rm)。
set -e
export PATH="$HOME/.orbstack/bin:$PATH"   # OrbStack 的 docker CLI
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE=fastlio_exp:noetic

exec docker run --rm -i $( [ -t 0 ] && echo -t ) \
    -v "$ROOT":/work \
    --shm-size=2g \
    "$IMAGE" bash -lc "${*:-bash}"
