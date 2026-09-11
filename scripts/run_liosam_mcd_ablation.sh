#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 5 || $# -gt 8 ]]; then
    echo "usage: $0 <FG-BA|FG-B0|GE-BA|GE-B0> <atv|handheld> <lidar-bag> <imu-bag> <output-dir> [start-s] [duration-s] [rate]" >&2
    exit 2
fi

VARIANT=$1
SETUP=$2
LIDAR_INPUT=$3
IMU_INPUT=$4
OUTPUT_INPUT=$5
START_S=${6:-0}
DURATION_S=${7:-30}
RATE=${8:-0.5}

PROJECT_ROOT=$(cd "$(dirname "$0")/.." && pwd)
resolve_inside_project()
{
    local input=$1
    if [[ "$input" = /* ]]; then
        printf '%s\n' "$input"
    else
        printf '%s\n' "$PROJECT_ROOT/$input"
    fi
}

LIDAR_HOST=$(resolve_inside_project "$LIDAR_INPUT")
IMU_HOST=$(resolve_inside_project "$IMU_INPUT")
OUTPUT_HOST=$(resolve_inside_project "$OUTPUT_INPUT")
for bag in "$LIDAR_HOST" "$IMU_HOST"; do
    if [[ ! -f "$bag" ]]; then
        echo "bag not found: $bag" >&2
        exit 2
    fi
done
if [[ "$SETUP" != atv && "$SETUP" != handheld ]]; then
    echo "unknown MCD setup: $SETUP" >&2
    exit 2
fi
if [[ "$SETUP" = atv ]]; then
    CALIBRATION="$PROJECT_ROOT/data/mcd/calib/atv_calib_file"
else
    CALIBRATION="$PROJECT_ROOT/data/mcd/calib/handheld_calib_file"
fi
if [[ -e "$OUTPUT_HOST/state_log.csv" ]]; then
    echo "refusing to overwrite completed output: $OUTPUT_HOST" >&2
    exit 2
fi

case "$VARIANT" in
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
CONTAINER_NAME="liosam_mcd_ablation_$$"
cleanup()
{
    set +e
    docker stop -t 5 "$CONTAINER_NAME" >/dev/null 2>&1
    rmdir "$LOCK_DIR" 2>/dev/null
}
trap cleanup EXIT INT TERM

mkdir -p "$OUTPUT_HOST"
OUTPUT_REL=${OUTPUT_HOST#"$PROJECT_ROOT"/}
LIDAR_REL=${LIDAR_HOST#"$PROJECT_ROOT"/}
IMU_REL=${IMU_HOST#"$PROJECT_ROOT"/}
if [[ "$OUTPUT_REL" = "$OUTPUT_HOST" || "$LIDAR_REL" = "$LIDAR_HOST" || "$IMU_REL" = "$IMU_HOST" ]]; then
    echo "bags and output must be inside project root" >&2
    exit 2
fi

BINARY="$PROJECT_ROOT/liosam_ws/devel/lib/lio_sam/$IMU_NODE"
MAPPING_BINARY="$PROJECT_ROOT/liosam_ws/devel/lib/lio_sam/lio_sam_mapOptmization"
LAUNCH="$PROJECT_ROOT/liosam_ws/src/LIO-SAM/launch/run_mcd_ablation.launch"
if [[ ! -x "$BINARY" ]]; then
    echo "binary not found: $BINARY" >&2
    exit 2
fi

{
    echo "variant=$VARIANT"
    echo "imu_node=$IMU_NODE"
    echo "dataset=mcd"
    echo "setup=$SETUP"
    echo "lidar_bag=$LIDAR_REL"
    echo "imu_bag=$IMU_REL"
    echo "start_s=$START_S"
    echo "duration_s=$DURATION_S"
    echo "rate=$RATE"
    echo "started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "liosam_commit=$(git -C "$PROJECT_ROOT/liosam_ws/src/LIO-SAM" rev-parse HEAD)"
    echo "gtsam_commit=79ace0dbde0d9fb74d82cec473330479b4e54276"
    echo "binary_sha1=$(shasum "$BINARY" | awk '{print $1}')"
    echo "mapping_binary_sha1=$(shasum "$MAPPING_BINARY" | awk '{print $1}')"
    echo "launch_file=liosam_ws/src/LIO-SAM/launch/run_mcd_ablation.launch"
    echo "launch_sha1=$(shasum "$LAUNCH" | awk '{print $1}')"
    echo "calibration_sha1=$(shasum "$CALIBRATION" | awk '{print $1}')"
    echo "omp_num_threads=1"
    echo "container_image=liosam_exp:noetic"
    echo "container_image_id=$(docker image inspect liosam_exp:noetic --format '{{.Id}}')"
} >"$OUTPUT_HOST/run_meta.txt"

docker run --rm --name "$CONTAINER_NAME" \
    -e OMP_NUM_THREADS=1 \
    -e OPENBLAS_NUM_THREADS=1 \
    -v "$PROJECT_ROOT:/work" \
    liosam_exp:noetic \
    bash /work/scripts/run_liosam_mcd_inside.sh \
    "$IMU_NODE" "/work/$LIDAR_REL" "/work/$IMU_REL" "/work/$OUTPUT_REL" \
    "$SETUP" "$START_S" "$DURATION_S" "$RATE"

echo "finished_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >>"$OUTPUT_HOST/run_meta.txt"
