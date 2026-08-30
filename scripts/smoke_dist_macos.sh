#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
APP="dist/mac/StockAnalysis.app"
BIN="$APP/Contents/MacOS/StockAnalysis"
[[ -x "$BIN" ]] || { echo "Missing $BIN" >&2; exit 1; }
TMP_DIR="$(mktemp -d -t '股票分析表 测试.XXXXXX')"
trap 'rm -rf "$TMP_DIR"' EXIT
export STOCK_ANALYSIS_HOME="$TMP_DIR/runtime"
"$BIN" --self-test --report "$TMP_DIR/self-test.json"
"$BIN" --headless --fixture-mode \
  --max-a-share-companies 4 --max-hk-companies 4 \
  --output "$TMP_DIR/fixture.xlsx"
.venv/bin/python scripts/validate_workbook.py "$TMP_DIR/fixture.xlsx"
"$BIN" --headless --fixture-mode \
  --max-a-share-companies 4 --max-hk-companies 4 \
  --output "$TMP_DIR/fixture-second-run.xlsx"
.venv/bin/python scripts/validate_workbook.py "$TMP_DIR/fixture-second-run.xlsx"
if [[ -d "$STOCK_ANALYSIS_HOME" ]] && \
  find "$STOCK_ANALYSIS_HOME" -type f \( -name '*.sqlite' -o -name '*.sqlite3' -o -name '*.db' \) \
    -print -quit | grep -q .; then
  echo "Persistent database unexpectedly created." >&2
  exit 1
fi
for legacy_dir in cache raw raw_responses; do
  [[ ! -e "$STOCK_ANALYSIS_HOME/$legacy_dir" ]] || {
    echo "Legacy cache directory unexpectedly created: $legacy_dir" >&2
    exit 1
  }
done
test -d "$APP/Contents/Resources"
find "$APP" -name '分析表.xlsx' -print -quit | grep -q .
find "$APP" -name 'libqcocoa.dylib' -print -quit | grep -q .
test -s dist/mac/logs/stock_analysis.log
open "$APP"
sleep 4
pkill -x StockAnalysis || true
if [[ -n "${CODESIGN_IDENTITY:-}" ]]; then
  codesign --deep --force --options runtime --sign "$CODESIGN_IDENTITY" "$APP"
fi
