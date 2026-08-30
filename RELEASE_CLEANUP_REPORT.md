# StockAnalysis 0.5.0 发布清理报告

日期：2026-08-30（Asia/Shanghai）

## 已完成的安全清理

- 已从当前工作树和 Git 索引移除 15,962 个旧版 `artifacts/` 跟踪文件，包括 0.2～0.4 的 PyInstaller build/dist 展开目录、旧 runtime/cache、旧 smoke、旧工作簿、旧截图和旧验证副本。
- 已删除过时的 0.3/0.4 根因、性能、构建、数据源和恢复检查点文档；当前说明统一为 0.5.0。历史内容仍可通过 Git commit 历史查看。
- 当前保留的审计产物仅为 0.5.0 的 `A_SHARE_REGRESSION.md`、`HK_COVERAGE_BASELINE.*`、`HK_COVERAGE_FINAL.*` 和最终 Top100 工作簿/运行报告。
- 清理脚本默认只做 dry-run；在当前 Windows、macOS arm64、macOS x86_64 三个 ZIP 全部存在前，拒绝执行最终本地发布清理。

## 当前待完成项

真实 macOS 双架构 artifact、完整工程 ZIP 和滚动 `current` Release 尚未在本报告这一提交前生成。安全顺序保持为：验证 Windows → 构建并下载两种 macOS 架构 → 生成完整工程 ZIP → 创建/验证 `current` → 再删除旧 Release/tag/Actions artifact 和剩余本地旧发布文件。

远端删除是不可恢复操作，将在当前替代产物可下载且哈希通过后单独确认并执行。本报告届时补充：

- 删除的本地旧发布目标数；
- 删除的旧 GitHub Releases 和 release tags；
- 删除的 Actions artifacts 数；
- 当前 commit SHA；
- 当前唯一 Release tag `current`；
- Windows/macOS 三个平台资产和 SHA-256。

## 历史安全性

Git commit 历史没有被 reset、rebase、filter 或强制改写；清理只形成普通删除提交。主分支和与发布无关的 tag/分支不会被删除。
