# macOS 构建交接

Windows 阶段只准备了跨平台代码、PyInstaller spec 和脚本，没有生成或宣称生成 macOS 应用。PyInstaller 产物不能跨操作系统构建，必须在真实 macOS 上执行以下步骤。

也可以在源码已提交并推送到可访问仓库后，手工触发 `.github/workflows/build-macos.yml`。workflow 必须 checkout 触发时的精确提交；当前未通过的真实网络门禁不得跳过。成功后下载完整 artifact 到项目的 `dist/mac`，再核对报告和 SHA-256。

## 前置条件

- macOS 13 或更高版本。
- 当前 Mac 原生架构的 64 位 Python 3.12。
- Apple Silicon 默认构建 arm64；Intel Mac 默认构建 x86_64。
- 不复用 Windows `.venv` 或 `build`。若工程已带真实 `dist/win` 发布物，可原样保留；Mac 脚本只写 `build/mac` 和 `dist/mac`。

## 首次准备

```bash
cd /path/to/StockAnalysis
rm -rf .venv
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e '.[dev]'
chmod +x scripts/*.sh
./scripts/build_mac.sh
```

也可先运行 `./scripts/bootstrap_macos.sh` 代替手动创建/安装步骤。`build_mac.sh` 内部会依次执行 `test_all.sh` 等价测试、PyInstaller 构建、两次 fixture 无缓存检查、GUI smoke、ZIP、SHA-256 和报告生成，不需要再重复运行 smoke 脚本。

## 目标产物

```text
dist/mac/StockAnalysis.app
dist/mac/StockAnalysis_macOS.zip
dist/mac/SHA256SUMS.txt
dist/mac/BUILD_REPORT_macOS.md
dist/mac/logs/stock_analysis.log
requirements-lock-macos.txt
```

`packaging/StockAnalysis.spec` 使用 onedir + windowed，并在 Darwin 上创建 `BUNDLE`。不要强行声明 universal2；只有 Python、PySide6 和全部二进制依赖都是 universal2 且两种架构实测通过时才考虑。

## 必做 smoke

```bash
dist/mac/StockAnalysis.app/Contents/MacOS/StockAnalysis --version
dist/mac/StockAnalysis.app/Contents/MacOS/StockAnalysis --self-test --report /tmp/stock-analysis-self-test.json
dist/mac/StockAnalysis.app/Contents/MacOS/StockAnalysis --headless --fixture-mode --max-a-share-companies 4 --max-hk-companies 4 --output "/tmp/股票分析表 fixture.xlsx"
open dist/mac/StockAnalysis.app
```

还要确认：

- `Contents` 内存在模板 `resources/templates/分析表.xlsx`；
- Qt `libqcocoa.dylib` 平台插件存在；
- 中文和空格路径自检/导出成功；
- GUI 启动后未立即退出，能开始/取消 fixture 任务；
- GUI 中 A 股和港股可分别切换“全部公司/总市值前 N 家”，未选中的复选框和单选框边界清楚；
- 生成一份双市场 Top 10 fixture/真实小样本，确认主表各 28 列且无技术状态列；
- `.app` 同级可创建 `logs/stock_analysis.log`，应用包内部不写运行数据；
- 用户目录只保存配置，不创建 SQLite、字段缓存、负缓存或原始响应缓存；
- ZIP 解压到另一目录后再次自检。

## 签名与公证

没有 Apple Developer ID 时，只生成供个人本机测试的未公证 `.app`，不要伪造签名状态。Gatekeeper 可能要求在 Finder 中右键“打开”。

若有真实证书，可在构建前设置：

```bash
export CODESIGN_IDENTITY='Developer ID Application: Example (TEAMID)'
```

脚本只在变量非空时调用 `codesign`。公证、staple 和发布证书验证需要在真实账户下另行执行并写入 `BUILD_REPORT_MACOS.md`。

## Mac 报告内容

- Mac 型号、macOS、CPU 架构、Python 和依赖版本。
- 全部命令与退出码、非网络/网络测试数。
- `.app` 自检、fixture、中文路径、GUI 和 cocoa 插件结果。
- `.app`/ZIP 路径和 SHA-256。
- 签名/公证的真实状态与已知限制。
