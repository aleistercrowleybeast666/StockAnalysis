# StockAnalysis 0.4.1 macOS 构建报告

日期：2026-08-30（Asia/Shanghai）

## 结果

发布状态：**阻断——尚无真实 macOS 产物**。

当前执行环境是 Windows，工程目录不是 Git 仓库，也没有可供 `workflow_dispatch` 检出的远端精确提交。因此本轮没有运行 macOS runner，以下文件均不存在，且没有创建空 `dist/mac` 或伪造哈希：

- `dist/mac/StockAnalysis.app`
- `dist/mac/StockAnalysis_macOS.zip`
- `dist/mac/SHA256SUMS.txt`
- `dist/mac/BUILD_REPORT_macOS.md`

## 已准备但未冒充执行的内容

- `.github/workflows/build-macos.yml`：`macos-14`、Python 3.12、隔离 `.venv`、严格离线/真实网络测试、PyInstaller、CLI/offscreen/GUI smoke、Cocoa 插件检查、ZIP、SHA-256 和 artifact 上传。
- `scripts/build_macos_onedir.sh`：拒绝非 Darwin，构建 `StockAnalysis.app` 后运行 smoke，再使用 `ditto` 打包。
- `scripts/smoke_dist_macos.sh`：检查程序、模板、`libqcocoa.dylib`、中文路径、两次无缓存 fixture、`.app` 同级日志和 GUI 启停。

macOS workflow 是严格门禁；在当前港股 22 日真实网络测试仍失败时应停止，不会生成正式 `.app`。只有把同一源码提交到可访问仓库、在真实 Mac 或 macOS runner 全部通过并下载 `dist/mac` 后，才能填写 Darwin 版本、CPU 架构、签名/公证状态和 SHA-256。
