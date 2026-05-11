#!/usr/bin/env bash
# Run the same checks CI runs, locally. Mirrors .github/workflows/ci.yml.
# Run from project root.
set -euo pipefail

if [ ! -f pyproject.toml ]; then
  echo "run this from the project root (where pyproject.toml lives)" >&2
  exit 1
fi

VENV_PY=${VENV_PY:-.venv/bin/python}
if [ ! -x "$VENV_PY" ]; then
  echo "creating .venv"
  python -m venv .venv
  "$VENV_PY" -m pip install --upgrade pip
  "$VENV_PY" -m pip install -r requirements.txt -r requirements-dev.txt
  "$VENV_PY" -m pip install -e . --no-deps
fi

echo "==> ruff"
"$VENV_PY" -m ruff check src tests scripts

echo "==> bandit"
"$VENV_PY" -m bandit -r src -ll -c pyproject.toml

echo "==> mypy (soft)"
"$VENV_PY" -m mypy src/npcreate_backend --ignore-missing-imports || true

echo "==> pytest"
PYTHONPATH=src "$VENV_PY" -m pytest

echo "==> pip-audit (production)"
"$VENV_PY" -m pip_audit -r requirements.txt --strict --progress-spinner off

echo
echo "all checks passed"
