#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
.venv/bin/python -m compileall -q src
.venv/bin/python -m ruff check .
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -m 'not network' --cov=stock_analysis --cov-report=term-missing
RUN_NETWORK_TESTS=1 .venv/bin/python -m pytest -m network -ra
