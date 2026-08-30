#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script must run on a real Mac." >&2
  exit 2
fi
ARCH_LABEL="${MACOS_ARCH_LABEL:-$(uname -m)}"
EXPECTED_UNAME="${MACOS_EXPECTED_UNAME:-$ARCH_LABEL}"
ACTUAL_UNAME="$(uname -m)"
if [[ "$ACTUAL_UNAME" != "$EXPECTED_UNAME" ]]; then
  echo "Runner architecture mismatch: expected $EXPECTED_UNAME, got $ACTUAL_UNAME." >&2
  exit 3
fi
VERSION="$(.venv/bin/python -c 'from stock_analysis.version import __version__; print(__version__)')"
APP="dist/mac/StockAnalysis.app"
BIN="$APP/Contents/MacOS/StockAnalysis"
ZIP="dist/mac/StockAnalysis_macOS_${ARCH_LABEL}.zip"
HASH_FILE="dist/mac/SHA256SUMS_${ARCH_LABEL}.txt"
REPORT="dist/mac/BUILD_REPORT_macOS_${ARCH_LABEL}.md"
ARCH_FILE="dist/mac/ARCHITECTURE_${ARCH_LABEL}.txt"
LOCK_FILE="dist/mac/requirements-lock-macos-${ARCH_LABEL}-resolved.txt"
./scripts/test_macos.sh
.venv/bin/python scripts/generate_version_info.py
.venv/bin/python -m PyInstaller --noconfirm --clean \
  --workpath build/mac --distpath dist/mac packaging/StockAnalysis.spec
if [[ -n "${CODESIGN_IDENTITY:-}" ]]; then
  codesign --deep --force --options runtime --sign "$CODESIGN_IDENTITY" "$APP"
  SIGNING_STATUS="Developer ID: $CODESIGN_IDENTITY"
else
  codesign --deep --force --sign - "$APP"
  SIGNING_STATUS="ad-hoc"
fi
codesign --verify --deep --strict "$APP"
./scripts/smoke_dist_macos.sh
rm -rf "$ROOT/dist/mac/logs"
rm -f "$ZIP" "$HASH_FILE" "$REPORT" "$ARCH_FILE" "$LOCK_FILE"
{
  echo "runner_label=${MACOS_RUNNER_LABEL:-local-mac}"
  echo "expected_architecture=$EXPECTED_UNAME"
  echo "uname=$(uname -m)"
  echo "macos=$(sw_vers -productVersion)"
  file "$BIN"
  codesign -dv --verbose=2 "$APP" 2>&1
} > "$ARCH_FILE"
ditto -c -k --sequesterRsrc --keepParent \
  "$APP" "$ZIP"
.venv/bin/python scripts/collect_release_artifacts.py \
  --platform macos --version "$VERSION" \
  --binary "$BIN" \
  --archive "$ZIP" \
  --hash-file "$HASH_FILE" \
  --report "$REPORT" \
  --architecture-file "$ARCH_FILE" \
  --signing-status "$SIGNING_STATUS" \
  --test-summary "offline suite and stable live-network smoke passed" \
  --smoke-summary "packaged CLI, Qt offscreen, fixture export, portable logs, and no-cache checks passed"
.venv/bin/python -m pip freeze > "$LOCK_FILE"
