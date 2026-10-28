#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
test_python=python3
if [ -x .agentmesh/venv/bin/python ]; then test_python=.agentmesh/venv/bin/python; fi
"$test_python" -m unittest discover -s tests -v
if [ -n "${AGENTMESH_NODE:-}" ]; then
  "$AGENTMESH_NODE" --test tests/scoped_write.test.mjs
elif command -v node >/dev/null; then
  node --test tests/scoped_write.test.mjs
fi
runtime_dir=scripts/agentmesh
if [ -f "$HOME/.omp/agentmesh/scripts/agentmesh/runtime.py" ]; then runtime_dir="$HOME/.omp/agentmesh/scripts/agentmesh"; fi
python3 "$runtime_dir/runtime.py" doctor
git diff --check

if [ "${1:-}" = "--live" ]; then
  python3 "$runtime_dir/smoke.py" --local --code
fi
