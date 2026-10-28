#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
python3 -m unittest discover -s tests -v
if [ -n "${AGENTMESH_NODE:-}" ]; then
  "$AGENTMESH_NODE" --test tests/scoped_write.test.mjs
elif command -v node >/dev/null; then
  node --test tests/scoped_write.test.mjs
fi
python3 scripts/agentmesh/runtime.py doctor
git diff --check

if [ "${1:-}" = "--live" ]; then
  python3 scripts/agentmesh/smoke.py --local --code
fi
