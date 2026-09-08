#!/bin/bash
# Build the architecture-independent Linux payload; no compiler or GTK required.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
PYTHON="${TRACKAI_PYTHON:-python3}"
echo "==> Checking Python sources and running core tests..."
"$PYTHON" -m compileall -q linux/src/trackai
"$PYTHON" -m unittest discover -s linux/tests -v
"$PYTHON" linux/scripts/package.py
echo "==> Built dist/trackai-linux.tar.gz"
