#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [[ ! -x .venv/bin/python ]]; then
  python3.12 -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip setuptools wheel
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -c 'import platform,sys,PySide6,PyInstaller; print(sys.version); print(platform.machine()); print(PySide6.__version__); print(PyInstaller.__version__)'

