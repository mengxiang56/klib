#!/usr/bin/env bash
set -euo pipefail

example_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
root=$(cd "$example_dir/.." && pwd)

exec "$root/run.sh" \
  AND2x2_ASAP7_6t_L \
  --library-name ASAP7_AND2_TOPOLOGY_EXAMPLE \
  --output-lib AND2x2_ASAP7_6t_L.lib
