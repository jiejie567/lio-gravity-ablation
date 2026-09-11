#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 || $# -gt 6 ]]; then
    echo "usage: $0 <UPSTREAM|FG-BA|FG-B0|GE-BA|GE-B0> <bag> <output-dir> [start-s] [duration-s] [rate]" >&2
    exit 2
fi

VARIANT=$1
BAG_INPUT=$2
OUTPUT_INPUT=$3
START_S=${4:-0}
DURATION_S=${5:-30}
RATE=${6:-1.0}

PROJECT_ROOT=$(cd "$(dirname "$0")/.." && pwd)
if [[ "$BAG_INPUT" = /* ]]; then
    BAG_HOST=$BAG_INPUT
else
    BAG_HOST="$PROJECT_ROOT/$BAG_INPUT"
fi
if [[ "$OUTPUT_INPUT" = /* ]]; then
    OUTPUT_HOST=$OUTPUT_INPUT
else
    OUTPUT_HOST="$PROJECT_ROOT/$OUTPUT_INPUT"
fi

if [[ ! -f "$BAG_HOST" ]]; then
    echo "bag not found: $BAG_HOST" >&2
    exit 2
fi
if [[ -e "$OUTPUT_HOST/state_log.csv" ]]; then
    echo "refusing to overwrite completed output: $OUTPUT_HOST" >&2
    exit 2
fi

case "$VARIANT" in
    UPSTREAM) IMU_NODE=lio_sam_imuPreintegration_upstream ;;
    FG-BA) IMU_NODE=lio_sam_imuPreintegration ;;
    FG-B0) IMU_NODE=lio_sam_imuPreintegration_fg_b0 ;;
    GE-BA) IMU_NODE=lio_sam_imuPreintegration_ge_ba ;;
    GE-B0) IMU_NODE=lio_sam_imuPreintegration_ge_b0 ;;
    *) echo "unknown variant: $VARIANT" >&2; exit 2 ;;
esac

LOCK_DIR="$PROJECT_ROOT/.run.lock"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    echo "another experiment holds $LOCK_DIR" >&2
    exit 3
fi

CONTAINER_NAME="liosam_ablation_$$"
cleanup()
{
    set +e
    docker stop -t 5 "$CONTAINER_NAME" >/dev/null 2>&1
    rmdir "$LOCK_DIR" 2>/dev/null
}
trap cleanup EXIT INT TERM

mkdir -p "$OUTPUT_HOST"
OUTPUT_REL=${OUTPUT_HOST#"$PROJECT_ROOT"/}
BAG_REL=${BAG_HOST#"$PROJECT_ROOT"/}
if [[ "$OUTPUT_REL" = "$OUTPUT_HOST" || "$BAG_REL" = "$BAG_HOST" ]]; then
    echo "bag and output must be inside project root for the container mount" >&2
    exit 2
fi

BINARY="$PROJECT_ROOT/liosam_ws/devel/lib/lio_sam/$IMU_NODE"
if [[ ! -x "$BINARY" ]]; then
    echo "binary not found: $BINARY" >&2
    exit 2
fi

{
    echo "variant=$VARIANT"
    echo "imu_node=$IMU_NODE"
    echo "dataset=m2dgr"
    echo "bag=$BAG_REL"
    echo "start_s=$START_S"
    echo "duration_s=$DURATION_S"
    echo "rate=$RATE"
    echo "started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "liosam_commit=$(git -C "$PROJECT_ROOT/liosam_ws/src/LIO-SAM" rev-parse HEAD)"
    echo "gtsam_commit=79ace0dbde0d9fb74d82cec473330479b4e54276"
    echo "binary_sha1=$(shasum "$BINARY" | awk '{print $1}')"
    echo "mapping_binary_sha1=$(shasum "$PROJECT_ROOT/liosam_ws/devel/lib/lio_sam/lio_sam_mapOptmization" | awk '{print $1}')"
    echo "launch_file=liosam_ws/src/LIO-SAM/launch/run_m2dgr_ablation.launch"
    echo "launch_sha1=$(shasum "$PROJECT_ROOT/liosam_ws/src/LIO-SAM/launch/run_m2dgr_ablation.launch" | awk '{print $1}')"
    echo "omp_num_threads=1"
    echo "container_image=liosam_exp:noetic"
    echo "container_image_id=$(docker image inspect liosam_exp:noetic --format '{{.Id}}')"
} >"$OUTPUT_HOST/run_meta.txt"

docker run --rm --name "$CONTAINER_NAME" \
    -e OMP_NUM_THREADS=1 \
    -e OPENBLAS_NUM_THREADS=1 \
    -v "$PROJECT_ROOT:/work" \
    liosam_exp:noetic \
    bash /work/scripts/run_liosam_inside.sh \
    "$IMU_NODE" "/work/$BAG_REL" "/work/$OUTPUT_REL" \
    "$START_S" "$DURATION_S" "$RATE"

echo "finished_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >>"$OUTPUT_HOST/run_meta.txt"
