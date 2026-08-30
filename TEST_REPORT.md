# StockAnalysis 0.4.1 测试报告

日期：2026-08-30（Asia/Shanghai）

## 总结

代码检查、103 项离线测试、Top100 真实运行、工作簿结构/视觉检查和 Windows 打包后 smoke 均已完成。真实网络测试为 7/8，通过的 7 项不抵消港股严格 22 日资金流失败；字段覆盖率还有三列 0%，因此发布状态是**阻断（Windows 产物仅供测试预览）**。

## 自动化结果

| 项目 | 结果 | 说明 |
|---|---|---|
| Ruff | 通过 | 全工程 `ruff check .` |
| compileall | 通过 | Python 3.12，`src` |
| 离线 pytest | 103 passed，8 deselected | 语句/分支综合覆盖率 79% |
| 最终定向回归 | 33 passed | 含覆盖率报告写入、进度、ETNet 年度完整性、A/H 流探测及失败隔离 |
| 进度延迟模拟 | 通过 | 中点 49.5%，最大单步 8.2 个百分点，单调到 100% |
| 真实网络 pytest | 7 passed，1 failed，102 deselected | 唯一失败：`test_live_eastmoney_hk_five_and_twenty_two_day_flow`；服务端未返回响应，严格 22 日值为空 |
| Top100 公司级流程 | 200 success | A 股 100 + 港股 100；不代表字段门禁通过 |
| Top100 字段门禁 | 失败 | 港股年度大宗两列、港股 22 日资金流为 0% |
| artifact-tool 结构/渲染 | 通过 | A 股、港股、数据来源说明三页已渲染检查；28 列、说明页换行与低覆盖着色正常 |
| Windows PyInstaller/smoke | 通过 | `--version`、FileVersion、ProductVersion 均 0.4.1；self-test、两次 fixture、中文空格路径、便携日志、GUI 启停通过 |
| macOS 原生构建 | 未执行 | 无真实 Mac/可触发仓库；不得视为通过 |

## 真实 Top100

- 输出：`artifacts/v3_live_top100_current.xlsx`
- 运行：48.209 秒；1,140 HTTP、1,104 成功、36 失败、12 重试。
- A 股重点六列：100%、100%、100%、100%、100%、99%。
- 港股重点六列：81%、81%、0%、0%、100%、0%。
- 三个 0% 字段被审计脚本正确返回为发布阻断，没有用 `-` 或 0 填充掩盖。

## Windows 预览产物

`scripts/build_windows_onedir.ps1` 默认严格停止。只有显式传入 `-PreviewAfterNetworkFailure`，并且 JUnit 证明失败全部是断言失败且基础设施错误数为 0 时，才继续生成带“阻断（测试预览）”标识的产物。本轮符合该条件；它不是正式发布绕过。

更详细的进度数据见 `PROGRESS_VALIDATION_REPORT.md`，字段审计见 `artifacts/COVERAGE_FINAL.md`。
