#!/usr/bin/env bash
set -euo pipefail

example_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
root=$(cd "$example_dir/.." && pwd)

exec "$root/run.sh" \
  NAND2x1_ASAP7_6t_L \
  --library-name ASAP7_NAND2_EXAMPLE \
  --output-lib NAND2x1_ASAP7_6t_L.lib
