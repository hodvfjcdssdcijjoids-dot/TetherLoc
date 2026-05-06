#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
echo "TetherLoc Linux folder: $(pwd)"

if [ ! -f tetherloc-env/bin/activate ]; then
  echo "Missing tetherloc-env. Run: bash install.sh"
  exit 1
fi

source tetherloc-env/bin/activate
echo "Running: python tetherloc_linux.py $*"
python tetherloc_linux.py "$@"
