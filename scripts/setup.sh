#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
command -v omp >/dev/null || { echo 'OMP is required'; exit 1; }
command -v uv >/dev/null || { echo 'Install uv first: brew install uv'; exit 1; }
uv venv --python 3.12 --allow-existing .agentmesh/venv
uv pip sync --python .agentmesh/venv/bin/python scripts/agentmesh/requirements.lock
.agentmesh/venv/bin/python scripts/agentmesh/download_model.py
.agentmesh/venv/bin/python scripts/agentmesh/install_global.py
.agentmesh/venv/bin/python "$HOME/.omp/agentmesh/scripts/agentmesh/runtime.py" doctor
