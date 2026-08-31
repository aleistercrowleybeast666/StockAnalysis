# StockAnalysis 0.6.0

StockAnalysis is a local PySide6 desktop application that generates annual A-share and Hong Kong stock analysis workbooks from public sources. It is intended for personal data organization and technical research, not investment advice.

## Current behavior

- A-share and Hong Kong scopes are independent. Each market defaults to all companies and can optionally be limited to its own Top N by current market capitalization.
- The Include-ST checkbox is enabled by default and only affects A shares.
- A-share money flow uses the latest 5/22 valid trading days; Hong Kong uses 5/20 days. The headers, calculations, provenance, and source guide use the same windows.
- Every run fetches fresh public data. There is no cross-run result, negative-result, or raw-response cache.
- Blank, `-`, and numeric zero have distinct meanings: unavailable/unverified, not applicable, and verified zero.
- Both market sheets include listing board, industry, and concept columns. Full concept mappings are preserved in a hidden detail sheet; Hong Kong theme/index tags are explicitly not presented as the same taxonomy as A-share concepts.
- Quote fallback is field-level, so a valid market capitalization no longer prevents a missing latest price from being retried and merged.
- BSE 920-series securities can fall back through the official BSE current-to-legacy code mapping for Tonghuashun concepts and 5/22-day money flow.
- The progress bar is indeterminate only while the security scope is unknown, then becomes a monotonic overall percentage based on selected markets, companies, and real request batches.
- The workbook has three visible sheets (`A股`, `港股`, and `数据来源说明`) plus hidden concept-detail, provenance, history, exception, and run-information sheets.

## Development

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap_windows.ps1
.venv\Scripts\python.exe -m pytest -m "not network"
$env:RUN_NETWORK_TESTS = "1"
.venv\Scripts\python.exe -m pytest -m network
```

Strict Windows onedir build:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows_onedir.ps1
```

Native macOS applications are built on real GitHub-hosted macOS runners through `.github/workflows/build-macos.yml`: `macos-15` for arm64 and `macos-15-intel` for x86_64. Windows does not fabricate `.app` bundles.

See [README_CN.md](README_CN.md) for the full user guide, [DATA_SOURCE_REPORT.md](DATA_SOURCE_REPORT.md) for current field coverage, and the platform build reports for verified artifacts and hashes.
