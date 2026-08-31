# StockAnalysis 0.6.0 macOS 双架构构建报告

日期：2026-09-01（Asia/Shanghai）

状态：**通过**

- GitHub Actions：`Build macOS #5`
- Workflow run ID：`33430887900`
- 构建提交：`9e6dcb5d4bdddcea5de58257a29b7d68102f384d`
- 总耗时：3 分 15 秒，2/2 jobs 成功
- arm64：`macos-15` / macOS 15.7.7 / Mach-O arm64
- x86_64：`macos-15-intel` / macOS 15.7.9 / Mach-O x86_64
- Python 3.12.10 / PySide6 6.11.2 / PyInstaller 6.22.2
- 两种架构均通过离线测试、稳定真实网络 smoke、PyInstaller `.app`、打包后 CLI/Qt/fixture/便携日志/无缓存 smoke、原生架构检查、ad-hoc `codesign --verify --deep --strict` 和 SHA-256 校验

| 文件 | 大小 | SHA-256 |
|---|---:|---|
| `dist/mac/StockAnalysis_macOS_arm64.zip` | 41,088,256 bytes | `0CB5E5A2BA053D4477E859121DD8A210496D4533B8FDFCBBE6A267C181F9CF5F` |
| `dist/mac/StockAnalysis_macOS_x86_64.zip` | 44,656,928 bytes | `3A45C4C1758DDB7C812C860CD0C54ED7CB7633A319E8123F7063361C71D4D6B0` |

下载后重新拼接 8 个分片并校验清单大小与哈希；两个 ZIP 的全量 CRC 均通过。每个归档均为 452 个条目、103 个符号链接，顶层只有 `StockAnalysis.app`，主程序权限为 `0755`，Info.plist 的 `CFBundleShortVersionString` 和 `CFBundleVersion` 均为 0.6.0。

归档内主二进制 SHA-256：

- arm64：`00F090CF25515BEAD5C797E25EF8F2327684F9E5B852D035ACE27E1110F15DEC`
- x86_64：`270CC4B7BB5C50ACF31EE53E87CEB486FC004D5B7BB2FE91D73F750AF4291597`

请在对应架构的 macOS 上完整解压 ZIP。不要先在 Windows 上展开再复制，否则 NTFS 会破坏 macOS 符号链接、可执行权限和签名结构。逐架构原始报告、架构证明、依赖快照和哈希清单位于 `dist/mac`。
