# StockAnalysis 0.5.0 Windows 构建报告

生成时间：2026-08-30T22:51:36+08:00
系统：Windows 11 10.0.26200
架构：AMD64
Python：3.12.13
PySide6：6.11.2
PyInstaller：6.22.2

## 结果

发布状态：**通过**

严格脚本依次通过 Ruff、`compileall`、118 项离线测试、9 项真实网络测试、PyInstaller onedir、打包后 `--version`/self-test、两次 fixture、中文和空格路径、仅依赖目录运行、便携日志与 GUI 启停 smoke。没有使用 `PreviewAfterNetworkFailure` 绕过参数。

程序输出版本、FileVersion 和 ProductVersion 均为 0.5.0。smoke 生成的日志已删除；ZIP 只保留绿色目录所需的空 `logs/` 目录，用户首次运行时在其中创建日志。

## 产物

| 文件 | 大小 | SHA-256 |
|---|---:|---|
| `dist/win/StockAnalysis/StockAnalysis.exe` | 7,972,917 bytes | `D6FD7BC2C262606936A02A041A8D6C57211DD5443014001ABB825036659124AC` |
| `dist/win/StockAnalysis_Windows_onedir.zip` | 62,994,001 bytes | `6A59707ECFB877703FE809D5454037037D4C82C68080046479DA2A6C0EFCC57E` |

ZIP 共 277 个条目，顶层只有 `StockAnalysis/`，包含 EXE、`_internal/` 和空 `logs/`。必须完整解压后运行，不能只复制主 EXE。原始机器生成报告与哈希位于 `dist/win/BUILD_REPORT_Windows.md` 和 `dist/win/SHA256SUMS.txt`。
