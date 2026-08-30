# 0.4.1 测试计划与结果

## 覆盖范围

1. Ruff、`compileall`、关键模块导入。
2. “全部公司”、A/H 独立 Top N、包含 ST、年度上限、上市状态过滤和证券池不足日志。
3. 不创建跨运行数据库/缓存；当前运行内相同请求去重。
4. HKEX 错误声明尺寸读取真实行、双柜台去重、A/H 行情代码隔离。
5. IPO 字段级状态、发行后股本解析、严格发行时市值计算。
6. A/H 大宗交易市场及单公司异常隔离、真零与空白语义、ETNet 年度完整性。
7. A/H 资金流 3 样本健康探测、5/22 日计算、只有 5 日时仅填 5 日。
8. 金融公司不适用、普通公司抓取失败、三年历史不足的显示语义。
9. 进度立即可见、不确定准备、时间权重、公司数推进、单调与跳变约束。
10. 工作簿前三张可见页、28 列、第三页实际覆盖率、隐藏审计页和整列 0% 发布门禁。
11. Windows 0.4.1 onedir 版本、自检、fixture、中文空格路径、便携日志、GUI、ZIP 和 SHA-256。
12. macOS workflow/spec 静态准备；真实 `.app`、Cocoa、架构、签名和公证必须在 Darwin 验收。

## 当前结果

- Ruff、`compileall`：通过。
- 离线 pytest：103 passed，8 deselected，覆盖率 79%。
- 真实网络 pytest：7 passed，1 failed；失败为港股严格 22 日资金流。
- Top100：公司级 200 success；字段门禁失败，港股年度大宗两列和 22 日资金流为 0%。
- Windows：测试预览构建和全部打包后 smoke 通过，版本 0.4.1。
- macOS：未执行原生构建，不得视为通过。

严格 Windows 命令：

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest -m "not network" -p no:cacheprovider
$env:RUN_NETWORK_TESTS = "1"
.\.venv\Scripts\python.exe -m pytest -m network -p no:cacheprovider
powershell -ExecutionPolicy Bypass -File .\scripts\build_win.ps1
```
