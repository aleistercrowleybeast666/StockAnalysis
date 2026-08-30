#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script must run on a real Mac." >&2
  exit 2
fi
VERSION="$(.venv/bin/python -c 'from stock_analysis.version import __version__; print(__version__)')"
./scripts/test_macos.sh
.venv/bin/python scripts/generate_version_info.py
.venv/bin/python -m PyInstaller --noconfirm --clean \
  --workpath build/mac --distpath dist/mac packaging/StockAnalysis.spec
./scripts/smoke_dist_macos.sh
rm -f dist/mac/StockAnalysis_macOS.zip dist/mac/SHA256SUMS.txt dist/mac/BUILD_REPORT_macOS.md
ditto -c -k --sequesterRsrc --keepParent \
  dist/mac/StockAnalysis.app dist/mac/StockAnalysis_macOS.zip
.venv/bin/python scripts/collect_release_artifacts.py \
  --platform macos --version "$VERSION" \
  --binary dist/mac/StockAnalysis.app/Contents/MacOS/StockAnalysis \
  --archive dist/mac/StockAnalysis_macOS.zip \
  --hash-file dist/mac/SHA256SUMS.txt \
  --report dist/mac/BUILD_REPORT_macOS.md
.venv/bin/python -m pip freeze > requirements-lock-macos.txt
