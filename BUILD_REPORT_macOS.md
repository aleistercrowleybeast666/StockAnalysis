# StockAnalysis 0.5.0 macOS 构建报告

状态：**等待当前精确提交的 GitHub Actions 原生构建**

Windows 不能交叉生成可信 `.app`。当前 workflow 已配置两个真实矩阵 job：

| Runner | 目标架构 | Python | 产物 |
|---|---|---|---|
| `macos-15` | arm64 | 3.12 | `StockAnalysis_macOS_arm64.zip` |
| `macos-15-intel` | x86_64 | 3.12 | `StockAnalysis_macOS_x86_64.zip` |

每个 job 必须通过离线测试、稳定真实网络 smoke、PyInstaller app、CLI/offscreen/fixture/便携日志/无缓存 smoke、`file` 架构检查、ad-hoc `codesign --verify` 和 SHA-256 校验。artifact 保留 1 天。

本文件不会预填或伪造 run ID、commit SHA、macOS 版本、架构证据和哈希。工作流完成并下载两个真实 artifact 后再更新；机器生成的逐架构报告同时保存在 `dist/mac`。
