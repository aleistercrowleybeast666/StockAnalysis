# StockAnalysis 0.4.1 Windows 构建与门禁报告

生成时间：2026-08-30 18:39:59（Asia/Shanghai）  
系统：Windows 11 x64（10.0.26200）  
Python：3.12.13；PySide6/Qt：6.11.2；PyInstaller：6.22.2。

## 结果

发布状态：**阻断（测试预览）**。

离线测试 103/103 通过；真实网络测试 7/8 通过，唯一失败为港股东方财富严格 5/22 日资金流测试。JUnit 显示 1 个断言失败、0 个基础设施错误，因此使用显式预览开关继续验证打包链。字段覆盖率门禁同时确认港股年度大宗交易两列和港股 22 日资金流为 0%。

PyInstaller onedir、内置模板、`--version`、self-test、两次 fixture、中文和空格路径、仅打包依赖运行、便携日志以及 GUI smoke 均通过。`StockAnalysis.exe` 的 FileVersion、ProductVersion 和程序输出版本均为 0.4.1。

## 产物

| 文件 | 大小 | SHA-256 |
|---|---:|---|
| `dist/win/StockAnalysis/StockAnalysis.exe` | 7,947,385 bytes | `E1A2BC01FF29E4AC0D1FBCF11590A681F064230E539D282C4D8B39535065BE6B` |
| `dist/win/StockAnalysis_Windows_onedir.zip` | 64,617,670 bytes | `BAE0776190A9F03E70FC71D574E2F26C4D2A4C909B9502CDDB410D4470BB4F4E` |

ZIP 共 277 个条目，包含 EXE、`_internal` 依赖、模板和空 `logs/` 目录；不含自检日志。必须完整解压后运行，不能只复制 EXE。

本报告不代表 macOS 构建通过，也不解除字段覆盖率门禁。
