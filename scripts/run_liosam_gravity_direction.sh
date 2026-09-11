#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 4 || $# -gt 7 ]]; then
    echo "usage: $0 <FG-BA|GE-BA> <bag> <output-dir> <direction-sigma-rad; <=0 disables> [start-s] [duration-s] [rate]" >&2
    exit 2
fi

VARIANT=$1
BAG_INPUT=$2
OUTPUT_INPUT=$3
DIRECTION_SIGMA=$4
START_S=${5:-0}
DURATION_S=${6:-60}
RATE=${7:-0.5}

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
if [[ ! "$DIRECTION_SIGMA" =~ ^-?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][-+]?[0-9]+)?$ ]]; then
    echo "direction sigma must be numeric: $DIRECTION_SIGMA" >&2
    exit 2
fi

case "$VARIANT" in
    FG-BA) BASE_IMU_NODE=lio_sam_imuPreintegration ;;
    GE-BA) BASE_IMU_NODE=lio_sam_imuPreintegration_ge_ba ;;
    *) echo "direction-factor pilot only admits FG-BA or GE-BA" >&2; exit 2 ;;
esac

LOCK_DIR="$PROJECT_ROOT/.run.lock"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    echo "another experiment holds $LOCK_DIR" >&2
    exit 3
fi

CONTAINER_NAME="liosam_gravity_direction_$$"
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
    echo "bag and output must be inside project root" >&2
    exit 2
fi

if awk -v value="$DIRECTION_SIGMA" 'BEGIN { exit(value > 0 ? 0 : 1) }'; then
    DIRECTION_MODE=ON
    if [[ "$VARIANT" = FG-BA ]]; then
        IMU_NODE=lio_sam_imuPreintegration_fg_ba_gdir
    else
        IMU_NODE=lio_sam_imuPreintegration_ge_ba_gdir
    fi
    DIRECTION_LOG="/work/$OUTPUT_REL/gravity_direction.csv"
else
    DIRECTION_MODE=OFF
    IMU_NODE=$BASE_IMU_NODE
    DIRECTION_LOG=""
fi

BINARY="$PROJECT_ROOT/liosam_ws/devel/lib/lio_sam/$IMU_NODE"
MAPPING_BINARY="$PROJECT_ROOT/liosam_ws/devel/lib/lio_sam/lio_sam_mapOptmization"
LAUNCH="$PROJECT_ROOT/liosam_ws/src/LIO-SAM/launch/run_m2dgr_ablation.launch"
if [[ ! -x "$BINARY" ]]; then
    echo "binary not found: $BINARY" >&2
    exit 2
fi

{
    echo "variant=$VARIANT"
    echo "imu_node=$IMU_NODE"
    echo "dataset=m2dgr"
    echo "gravity_direction_mode=$DIRECTION_MODE"
    echo "gravity_direction_sigma_rad=$DIRECTION_SIGMA"
    echo "gravity_direction_source=sensor_msgs/Imu.orientation"
    echo "bag=$BAG_REL"
    echo "start_s=$START_S"
    echo "duration_s=$DURATION_S"
    echo "rate=$RATE"
    echo "started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "liosam_commit=$(git -C "$PROJECT_ROOT/liosam_ws/src/LIO-SAM" rev-parse HEAD)"
    echo "gtsam_commit=79ace0dbde0d9fb74d82cec473330479b4e54276"
    echo "binary_sha1=$(shasum "$BINARY" | awk '{print $1}')"
    echo "mapping_binary_sha1=$(shasum "$MAPPING_BINARY" | awk '{print $1}')"
    echo "launch_file=liosam_ws/src/LIO-SAM/launch/run_m2dgr_ablation.launch"
    echo "launch_sha1=$(shasum "$LAUNCH" | awk '{print $1}')"
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
    "$START_S" "$DURATION_S" "$RATE" "$DIRECTION_SIGMA" \
    "$DIRECTION_LOG"

echo "finished_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >>"$OUTPUT_HOST/run_meta.txt"
