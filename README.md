# StockAnalysis 0.4.1

StockAnalysis is a local PySide6 desktop application that creates auditable annual A-share and Hong Kong stock analysis workbooks from public data. It is a data-preparation tool, not investment advice.

Version 0.4.1 includes independent checkbox-based all-company/Top-N scopes, an Include-ST option, no cross-run cache, field-level provenance, strict blank/`-`/zero semantics, A/H runtime source probing, a monotonic time-weighted overall progress bar, and a visible per-run coverage report in the third worksheet.

Current release status is **blocked**. The Windows 0.4.1 onedir build passed offline tests and packaged smoke checks, but it is labeled as a test preview because three HK fields still have 0% coverage. No native macOS app has been produced.

## Windows

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap_windows.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\build_win.ps1
```

The strict build stops when live network gates fail. The current test preview is under `dist/win`; keep the entire onedir folder. Frozen logs are written beside the executable and `_internal` at `StockAnalysis/logs/stock_analysis.log`.

## macOS

PyInstaller cannot cross-build a genuine macOS application on Windows. On a real target-architecture Mac, run:

```bash
./scripts/bootstrap_macos.sh
./scripts/build_mac.sh
```

The repository also includes `.github/workflows/build-macos.yml` for manual `macos-14` builds. It must run from an exact committed revision and pass strict tests before a `dist/mac` artifact is accepted.

See [README_CN.md](README_CN.md), [DATA_SOURCE_REPORT.md](DATA_SOURCE_REPORT.md), [TEST_REPORT.md](TEST_REPORT.md), and [BUILD_REPORT_macOS.md](BUILD_REPORT_macOS.md).
