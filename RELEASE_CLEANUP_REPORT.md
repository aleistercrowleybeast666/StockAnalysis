# StockAnalysis 0.6.0 发布清理报告

日期：2026-09-01（Asia/Shanghai）

## 已完成的安全清理

- Git 当前索引不再跟踪 0.5.0 Top100 工作簿；本地旧文件保留，历史仍可通过 Git commit 查看。
- 当前仓库正式跟踪 0.6.0 Top100、双市场全量工作簿、运行报告和覆盖率证据。
- `dist/win` 已由严格脚本重新生成；`dist/mac` 的旧解压目录已删除，只保留两个未展开的 0.6.0 原生 ZIP、逐架构证明与哈希文件。
- Git 历史没有 reset、rebase、filter 或强制改写；全部改动均为普通提交。

## GitHub 远端状态

已登录账号确认其本人拥有私有仓库 `aleistercrowleybeast666/StockAnalysis`。仓库当前没有 `current` Release（`releases/tag/current` 返回 404），也没有可供清理的旧 Release 资产；因此本轮没有执行任何远端删除，也没有伪造“已清理”记录。

GitHub Actions run `33430887900` 的 18 个短期传输 artifact 保留为构建证据，并受工作流 `retention-days: 1` 自动过期策略约束。本轮未手工删除 Actions artifact。

创建新的 rolling `current` Release 属于新的远端发布动作，不由附件中的清理文字单独授权；本轮只完成用户明确要求的双平台构建、下载、校验与 `dist` 整理。如需创建并上传 `current` Release，可在用户明确确认后执行。
