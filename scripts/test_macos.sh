#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
.venv/bin/python -m compileall -q src
.venv/bin/python -m ruff check .
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -m 'not network' --cov=stock_analysis --cov-report=term-missing
RUN_NETWORK_TESTS=1 .venv/bin/python -m pytest -q \
  tests/test_network_sources.py::test_live_etnet_hk_complete_year_block_trade_sample \
  tests/test_network_sources.py::test_live_eastmoney_hk_five_and_twenty_day_flow \
  tests/test_network_sources.py::test_live_tradego_hk_five_and_twenty_day_flow
