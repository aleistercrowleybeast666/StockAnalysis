# StockAnalysis 0.4.1 构建状态

Windows 11 x64 上已生成并验证 0.4.1 onedir 测试预览。离线测试 103/103 通过，真实网络测试 7/8 通过，打包后版本资源、自检、fixture、中文空格路径、便携日志和 GUI smoke 通过。

正式发布门禁未通过：港股 2025 年度大宗/大额交易笔数与金额为 0% 覆盖，港股严格最近 22 个交易日资金流为 0% 覆盖。Windows 产物因此明确标记为“阻断（测试预览）”。

Windows 产物、大小和哈希见根目录 `BUILD_REPORT_Windows.md` 以及 `dist/win/BUILD_REPORT_Windows.md`。

当前没有真实 `dist/mac/StockAnalysis.app`。工程提供严格的 `macos-14` workflow 和原生脚本，但当前目录不是 Git 仓库，无法触发精确提交构建。详情见根目录 `BUILD_REPORT_macOS.md`。
