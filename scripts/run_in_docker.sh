#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
root=$(cd "$script_dir/.." && pwd)
mode=${1:?Usage: run_in_docker.sh <spice|gds> <config> <work-dir> <spice-input> [gds-dir]}
config=${2:?Usage: run_in_docker.sh <spice|gds> <config> <work-dir> <spice-input> [gds-dir]}
work_dir=${3:?Usage: run_in_docker.sh <spice|gds> <config> <work-dir> <spice-input> [gds-dir]}
spice_input=${4:?Usage: run_in_docker.sh <spice|gds> <config> <work-dir> <spice-input> [gds-dir]}
gds_dir=${5:-}

config=$(realpath "$config")
work_dir=$(realpath "$work_dir")
spice_input=$(realpath "$spice_input")
asset_root=$(realpath "${KLIB_ASSET_ROOT:?KLIB_ASSET_ROOT is not set}")
image=${KLIB_DOCKER_IMAGE:-centos7-stdcell}

mounts=(
  -v "$root:$root:ro"
  -v "$work_dir:$work_dir"
  -v "$asset_root:$asset_root:ro"
  -v "$spice_input:$spice_input:ro"
)
if [[ "$mode" == gds ]]; then
  if [[ -z "$gds_dir" ]]; then
    echo "gds mode requires a GDS directory" >&2
    exit 2
  fi
  gds_dir=$(realpath "$gds_dir")
  mounts+=(-v "$gds_dir:$gds_dir:ro")
fi

docker run --rm \
  --privileged \
  --cap-add=NET_ADMIN \
  --hostname=eda \
  -e "CHAR_THREADS=${CHAR_THREADS:-8}" \
  -e LM_LICENSE_FILE \
  -e CDS_LIC_FILE \
  -e "KLIB_ASSET_ROOT=$asset_root" \
  "${mounts[@]}" \
  --workdir "$work_dir" \
  "$image" \
  /bin/bash "$root/scripts/run_pipeline.sh" \
  "$mode" "$config" "$work_dir"

