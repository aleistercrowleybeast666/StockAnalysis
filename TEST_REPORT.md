# StockAnalysis 0.5.0 测试报告

日期：2026-08-30（Asia/Shanghai）

## 自动化与真实数据

| 门禁 | 结果 | 证据 |
|---|---|---|
| Ruff / `compileall` | 通过 | 全工程静态检查通过 |
| 离线 pytest | 通过 | 118 passed，9 deselected；Windows 严格构建覆盖率 80% |
| 真实网络 pytest | 通过 | 9 passed，118 deselected；覆盖 A/H 名单、行情、财务、发行、大宗交易和 5/22、5/20 日资金流 |
| 双市场 Top100 | 通过 | 200 家成功、部分缺失 0、失败 0、排除 0；整列数值门禁通过 |
| 工作簿结构/公式 | 通过 | 三张可见页、四张隐藏审计页；A/H 各 100 行、28 列；无公式错误 |
| 工作簿视觉 | 通过 | A 股、港股、第三页覆盖表和静态来源矩阵均已渲染检查，无明显裁切或不可读区域 |
| A 股回归 | 通过 | 表头仍为 22 日；目标字段 100%，22 日资金流 99%；见 `artifacts/A_SHARE_REGRESSION.md` |
| 港股窗口 | 通过 | 表头和计算均为 5/20 日，两个资金流字段均 100% |
| 港股金融分类 | 通过 | 毛利率相关字段 72 数值 + 28 `-` + 0 空白 |
| 港股年度大额交易 | 通过真实性门禁 | 6 个数值（5 非零、1 真零）、9 个不适用、85 个区间不完整空白；不再整列为空 |
| 进度 | 通过 | 70% 位于墙钟 74.55%；末 10% 占 1.19%；最大跳变 5%；单调到 100% |

## Windows 打包后验收

严格构建 `scripts/build_windows_onedir.ps1` 通过：

- 程序输出版本、FileVersion、ProductVersion 均为 0.5.0；
- self-test；
- 两次 fixture 生成和工作簿校验；
- 中文与空格路径；
- 复制完整 onedir 后缩减 PATH 运行；
- EXE/依赖目录同父目录的绿色日志；
- 无 SQLite/JSON 跨运行结果缓存；
- GUI 启动并安全结束；
- ZIP 内容和 SHA-256 复核。

Windows 状态：**通过**。详见 `BUILD_REPORT_Windows.md`。

## macOS 原生验收

工作流已配置 `macos-15` arm64 和 `macos-15-intel` x86_64 两个真实 runner。每个 job 会重跑离线套件和 3 项稳定网络 smoke、构建 `.app`、执行 offscreen/fixture/日志/无缓存 smoke、ad-hoc codesign、架构检查和 ZIP 哈希校验。

本报告提交前的状态为：**等待本精确提交的 GitHub Actions 原生构建结果**。真实 run ID、commit SHA、架构证据和哈希将在 `BUILD_REPORT_macOS.md` 及下载后的 `dist/mac` 报告中记录；未取得真实 artifact 前不会声明双平台完成。
