#!/usr/bin/env bash

# 遇到错误、未定义变量或管道中的失败时立即退出，避免流程带错继续执行。
set -euo pipefail

# 确定仓库根目录，并读取唯一必需的位置参数：cell 名。
root=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cell_name=${1:?Usage: run.sh <cell-name> [options]}
shift

# cell 名只用于匹配 input/ 下的同名文件，不允许用它传入其他目录。
if [[ "$cell_name" == */* ]]; then
  echo "cell name must not contain a path separator: $cell_name" >&2
  exit 2
fi

# 约定所有输入都在 input/，中间文件和最终结果写入 lib-<cell名>/。
input_dir="$root/input"
gds_dir="$input_dir"
work_dir="$root/output/$cell_name"

# 在 input/ 中查找与 cell 同名的 SPICE/CDL 文件。
# 支持常见的 .sp、.spi、.spice、.cdl 和 .netlist 扩展名，文件名匹配不区分大小写。
spice_matches=()
for candidate in "$input_dir"/*; do
  [[ -f "$candidate" ]] || continue
  filename=${candidate##*/}
  stem=${filename%.*}
  extension=${filename##*.}
  case "${extension,,}" in
    sp|spi|spice|cdl|netlist) ;;
    *) continue ;;
  esac
  if [[ "${stem,,}" == "${cell_name,,}" ]]; then
    spice_matches+=("$candidate")
  fi
done

# 必须且只能找到一个同名 SPICE/CDL，避免选错源网表。
if (( ${#spice_matches[@]} == 0 )); then
  echo "missing SPICE/CDL for $cell_name under $input_dir" >&2
  exit 2
fi
if (( ${#spice_matches[@]} > 1 )); then
  printf 'expected one SPICE/CDL for %s under %s, found:\n' \
    "$cell_name" "$input_dir" >&2
  printf '  %s\n' "${spice_matches[@]}" >&2
  exit 2
fi
spice_input=${spice_matches[0]}

# 创建本次运行的工作目录，配置文件也会生成到这里。
mkdir -p "$work_dir"
work_dir=$(realpath "$work_dir")
config="$work_dir/cells.generated.json"

# 默认使用仓库自带的工艺规则、模型和辅助脚本；外部环境变量仍可覆盖此路径。
export KLIB_ASSET_ROOT="${KLIB_ASSET_ROOT:-$root/assets}"

# 解析 SPICE 中的指定 cell、检查同名 GDS，并生成后续流程使用的 JSON 配置。
# cell 名之后传入 run.sh 的其他参数会原样交给配置生成器。
python3 "$root/scripts/generate_cell_config.py" \
  --mode gds \
  --gds-dir "$gds_dir" \
  --output "$config" \
  --cell "$cell_name" \
  "$spice_input" "$@"

# 默认在 Docker 中执行 LVS、PEX 和 Liberty 表征。
# 设置 KLIB_EXECUTION=local 时，可直接在当前已安装 EDA 工具的环境中运行。
case "${KLIB_EXECUTION:-docker}" in
  docker)
    exec bash "$root/scripts/run_in_docker.sh" \
      gds "$config" "$work_dir" "$spice_input" "$gds_dir"
    ;;
  local)
    exec bash "$root/scripts/run_pipeline.sh" \
      gds "$config" "$work_dir"
    ;;
  *)
    echo "KLIB_EXECUTION must be docker or local" >&2
    exit 2
    ;;
esac
