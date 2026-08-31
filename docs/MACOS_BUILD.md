# macOS 原生构建说明（0.6.0）

Windows 不能交叉生成可信 `.app`。正式 macOS 产物必须由真实 Darwin 环境构建，并保留 runner、架构、测试、签名和二进制 `file` 证据。

## GitHub Actions

手工触发 `.github/workflows/build-macos.yml`。矩阵为：

- `macos-15` → arm64；
- `macos-15-intel` → x86_64。

每个 job checkout 被触发的精确 commit，安装 Python 3.12 与 `requirements-lock-macos.txt`，运行 118 项离线测试和 3 项稳定真实网络 smoke，使用 PyInstaller 生成 windowed `.app`，执行 CLI/offscreen/fixture/便携日志/无缓存 smoke，进行 ad-hoc codesign，记录 `uname -m`、`sw_vers`、`file`、依赖版本和 SHA-256，再上传保留 1 天的 artifact。

产物名称：

```text
StockAnalysis_macOS_arm64.zip
StockAnalysis_macOS_x86_64.zip
SHA256SUMS_arm64.txt
SHA256SUMS_x86_64.txt
BUILD_REPORT_macOS_arm64.md
BUILD_REPORT_macOS_x86_64.md
ARCHITECTURE_arm64.txt
ARCHITECTURE_x86_64.txt
```

下载验证后整理到 `dist/mac/arm64`、`dist/mac/x86_64` 和两个稳定 ZIP。最终 runner、run ID、commit SHA 与哈希见根目录及 `dist/mac` 的构建报告。

## 本机真实 Mac

```bash
./scripts/bootstrap_macos.sh
./scripts/build_macos_onedir.sh
```

默认签名是 ad-hoc，不代表 Apple Developer ID、公证或 Gatekeeper 分发许可。需要正式外部分发时应另行配置证书和 notarization。
