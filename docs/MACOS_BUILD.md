# macOS 构建说明（0.4.1）

当前没有真实 macOS `.app`。Windows 阶段只验证了跨平台源码、spec、shell 脚本和 workflow 的存在，不能替代 Darwin 原生构建。

真实 Mac 流程：

```bash
./scripts/bootstrap_macos.sh
./scripts/build_mac.sh
```

GitHub Actions 流程位于 `.github/workflows/build-macos.yml`，仅支持从仓库中的精确提交手工触发。它会在 `macos-14` 上安装 Python 3.12、运行严格测试、构建/检查 `.app`、打包 ZIP、校验 SHA-256 并上传完整 `dist/mac`。

当前真实网络门禁仍失败，因此 workflow 应严格停止，不能为了得到 `.app` 而跳过测试。详细交接和签名限制见 `MACOS_HANDOFF.md`，当前阻断见根目录 `BUILD_REPORT_macOS.md`。
