#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
mode=${1:?Usage: run_pipeline.sh <spice|gds> <config.json> <work-dir>}
config=${2:?Usage: run_pipeline.sh <spice|gds> <config.json> <work-dir>}
work_dir=${3:?Usage: run_pipeline.sh <spice|gds> <config.json> <work-dir>}

if [[ "$mode" != spice && "$mode" != gds ]]; then
  echo "mode must be spice or gds" >&2
  exit 2
fi

config=$(realpath "$config")
mkdir -p "$work_dir"
work_dir=$(realpath "$work_dir")

python3 "$script_dir/flow.py" prepare \
  --mode "$mode" --config "$config" --work-dir "$work_dir"

stdgen_bin=
stdgen_libs=
if [[ "$mode" == spice ]]; then
  stdgen_bin=$(python3 "$script_dir/flow.py" asset --config "$config" --name stdgen_bin)
  stdgen_libs=$(python3 "$script_dir/flow.py" asset --config "$config" --name stdgen_libs)
fi

while IFS=$'\t' read -r key cell; do
  run="$work_dir/runs/$key"
  if [[ "$mode" == spice ]]; then
    (
      cd "$run/SDCgen"
      LD_LIBRARY_PATH="$stdgen_libs:${LD_LIBRARY_PATH:-}" \
        "$stdgen_bin" config.json 0 >"$run/logs/stdgen.log" 2>&1
    )
    test -s "$run/gds/$cell.gds2" || {
      echo "StdGen did not create $cell.gds2" >&2
      exit 20
    }
    mv -f "$run/gds/$cell.gds2" "$run/gds/$cell.gds"
  fi

  (
    cd "$run/pex"
    calibre -lvs -hier -spice "./svdb/$cell.sp" \
      -turbo 8 -turbo_all -nowait pex.rule >pex.log 2>&1
    test -s "$cell.lvs.report" || {
      echo "missing LVS report for $cell" >&2
      exit 21
    }
    sed -n '/OVERALL COMPARISON RESULTS/,+24p' "$cell.lvs.report" |
      grep -Eq '#[[:space:]]+CORRECT' || {
        echo "LVS is not CORRECT for $cell" >&2
        exit 22
      }
    calibre -xact -3d -pdb -rcc -turbo 8 -turbo_all -nowait pex.rule >>pex.log 2>&1
    calibre -xact -fmt -all -nowait pex.rule >>pex.log 2>&1
    test -s "$cell.pex.netlist" || {
      echo "missing PEX netlist for $cell" >&2
      exit 23
    }
  )
done < <(python3 "$script_dir/flow.py" list --config "$config")

python3 "$script_dir/flow.py" generate-char \
  --config "$config" --work-dir "$work_dir"

output_lib=$(python3 - "$config" "$work_dir" <<'PY'
import json
import pathlib
import sys
config = json.load(open(sys.argv[1]))
print(pathlib.Path(sys.argv[2]) / "characterization" / "output" / config["output_lib"])
PY
)

(
  cd "$work_dir/characterization"
  liberate char.tcl >output/char.log 2>&1
)
test -s "$output_lib" || {
  echo "Liberate did not produce $output_lib" >&2
  exit 30
}
if grep -Eq 'Number of failing cells[[:space:]]*=[[:space:]]*[1-9]' \
  "$work_dir/characterization/output/char.log"; then
  echo "Liberate reports failing cells" >&2
  exit 31
fi

area_tool=$(python3 "$script_dir/flow.py" asset --config "$config" --name area_tool)
: >"$work_dir/characterization/output/area.log"
while IFS=$'\t' read -r key cell; do
  python3 "$area_tool" "$cell" \
    --gds "$work_dir/runs/$key/gds/$cell.gds" \
    --cell "$cell" --lib "$output_lib" --update-lib --area-engine python \
    >>"$work_dir/characterization/output/area.log"
done < <(python3 "$script_dir/flow.py" list --config "$config")

printf 'PASS %s\n' "$output_lib"

