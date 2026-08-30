# Changelog

## 0.4.1 - 2026-08-30

- 发行资料改为字段级状态；A 股通过东方财富历史股本和同花顺上市日股本补全发行后总股本，港股使用东方财富历史股本，发行时总市值/增长率 Top100 覆盖分别达到 A 股 100%/100%、港股 81%/81%。
- A/H 大宗交易按市场和单公司隔离；A 股 Top100 完整覆盖，其中 84 家非零、16 家确认零，不再因港股异常丢失。
- 实现 ETNet 港股大额成交列表/明细解析和年度完整性边界；无法证明 2025 全年时保持空白，不写假零。
- A/H 历史资金流各使用最多 3 家运行内健康探测。A 股改用同花顺每日资金面备源后 5/22 日覆盖为 100%/99%；港股 TradeGo/AASTOCKS 取得 5 日值，但 20 日不冒充 22 日。
- 第三页增加本次覆盖率、实际来源成功数、主要空白原因、行情日期和资金流截止日；整列 0% 由审计脚本明确阻断发布。
- 进度条在准备阶段立即显示不确定模式，证券池确定后按时间权重和实际公司数单向累计；延迟模拟中点 49.5%，真实 Top100 墙钟中点显示 51%。
- Windows EXE、FileVersion 和 ProductVersion 统一为 0.4.1，已生成明确标记“阻断（测试预览）”的 onedir/ZIP/hash；严格构建默认仍会在网络门禁失败时停止。
- 增加 `macos-14` 手工 workflow。当前没有真实 Mac/可触发 Git 仓库，未生成或伪造 `dist/mac`；完整双平台工程 ZIP 因此仍被阻断。

## 0.4.0 - 2026-08-30

- 保留范围文案“全部公司”和独立“包含 ST”选项；A 股、港股默认均为全部公司，也可分别勾选“总市值前 N 家”，互不补足、互不分摊。
- 删除跨运行 SQLite、字段、负缓存和原始响应缓存；每次运行重新访问数据源，仅在本次运行内去重相同请求。
- 删除已无意义的“更新方式”和手工资金流模式。资金流改为 A 股、港股自动尝试；不足 22 个有效交易日时留空并写明原因，不以单日数据冒充 5/22 日累计。
- 删除运行级端点熔断。单家公司请求只做有限重试，失败不会让后续公司直接显示“已熔断”。
- A 股证券池优先沪深北交易所，港股优先 HKEX；行情主源缺失真实时间或失败时，A 股回退腾讯、港股回退 AASTOCKS。修复 A/H 混合批量行情代码碰撞和 HKEX 双柜台重复。
- 最新市值标题和记录使用来源真实行情日期，不再用本机日期填充。分析年度上限仍为系统当前年份减一，因此进入下一年后可选择本年。
- IPO 市值只在同时取得发行价和明确的发行后总股本时计算；缺失、失败、不适用和真实零值分别显示为空白、审计原因、`-` 和 `0`。
- 工作簿前三张可见表固定为 `A股`、`港股`、`数据来源说明`，其余溯源和异常表隐藏；第三页扩展为 11 列来源/回退/口径矩阵，并支持按最新总市值或分析年度营业收入排序。
- 进度按实际公司数和请求工作量统一规划，准备阶段不预占固定百分比，逐公司阶段在整次任务内累计且单向前进。
- 版本提升到 0.4.0；Windows onedir 输出到 `dist/win`，macOS 原生构建输出到 `dist/mac`，Windows 不伪造 Mac 产物。

## 0.3.2 - 2026-08-30

- 将未勾选市值限制时的范围文案统一为“全部公司”，并明确忽略隐藏的 Top N 数值；保留对旧版“全部正常上市公司”配置值的兼容迁移。
- 财务阶段在 A 股、港股及“全部公司”的多个批次之间使用本次任务累计计数，不再每批从 1/200 重新显示。
- 删除 GUI 中按阶段预设的固定百分比。证券池确定后，按实际证券数量、最终候选数量及行情批量/逐公司请求成本建立整次工作量计划；准备扫描不预占百分比，完成一家公司或一批工作即累计总进度。
- 冻结版日志现在即使设置 `STOCK_ANALYSIS_HOME` 也始终保留在 EXE 与依赖目录的共同父目录；该变量只重定向数据库与缓存，便携日志位置不再漂移。
- 增加 450 家“全部公司”模拟回归，验证累计财务进度、总进度单调性，以及行情扫描不会固定跳到 20%～30%。

## 0.3.0 - 2026-08-29

- 将 A 股和港股范围分别改为“全部公司”或“总市值前 N 家”，按完整证券池的最新总市值排序，并对核心财务缺失候选自动补位。
- 修复东方财富证券列表请求 500 行但服务端实际仅返回 100 行时被误判为完整页的问题；A 股真实证券池恢复到 5905 家，并将异常小证券池阈值和缓存版本升级。
- 简化 GUI，只保留财务年度、两市范围、A 股资金流和输出目录；隐藏缓存、网络、并发、ST/金融和测试模式等实现配置。
- 主表改为 28 个业务列，删除字段/公司状态；缺失和不适用显示 `—`，真实零值显示 0，A 股无大宗交易显示 0/0.00。
- 金融企业继续入选，毛利率按不适用处理；港股可选发行资料、大宗交易和资金流缺失不再制造用户可见错误。
- 证券池、分类、财务、行情、发行、大宗交易、资金流和汇率缓存全部版本化；缺失使用 6 小时 TTL，错误使用 15 分钟 TTL。
- 修复缓存与原始响应并发写同一 SQLite 连接时偶发 `cannot commit - no transaction is active`，两者改用共享可重入锁。
- 资金流切换到 `fflow/kline` 兼容路径并升级缓存版本；关闭时严格 0 请求，服务断连时有限重试/熔断且不阻断主任务。
- 完成 77 个离线测试、4 个真实网络测试、真实 A/HK Top 10/100、双市场冷/温缓存、最终工作簿和 Windows onedir/EXE 验证。

## 0.2.2 - 2026-08-29

- 删除总目标公司数及其动态均分/补足逻辑，只保留 A 股、港股两个互不影响的最大公司数；0 表示全部。
- 证券池准备阶段改为总量未知的不定进度，不再占用固定百分比。
- 按实际请求成本和资金流模式重新分配总进度权重，重点留给逐公司财务、发行信息和完整资金流阶段。
- 为更新方式、资金流模式、网络模式及运行结果统计增加界面悬停说明。

## 0.2.1 - 2026-08-29

- 为普通复选框和可勾选分组框增加清晰的未选中边框、蓝底白勾及禁用状态。
- 将 GUI 的浅蓝强调色统一为“开始生成”按钮默认蓝 `#3B82F6`，交互态使用更深蓝色。
- 将进度条改为覆盖证券池、采集、计算、校验和导出的整次任务总进度，跨阶段单调递增。

## 0.2.0 - 2026-08-29

- 将总目标公司数改为两市动态均分/补足，并增加 A 股、港股独立上限。
- 修复 HKEX XLSX 声明尺寸过小导致少读行，以及异常小证券池缓存未重抓。
- 将行情改为每批最多 100 个指定证券的混合市场请求；大宗交易改为全市场年度分页阶段，并增加资金流三种模式。
- 对当前网络中会主动断连的 `push2` 主机改用同源 `push2delay` 结构化端点；保留有限重试、熔断与负缓存。
- 增加国内源直连优先、分端点熔断、15 分钟负缓存、请求与阶段统计。
- 增加可选巨潮注册 API 主源及东方财富自动回退与溯源。
- 公司/字段状态改为 Python 内部计算，港股允许缺失与排除规则显式化。
- 工作簿改为 30 列双层分组表头；GUI 改用统一明亮蓝/浅蓝主题。
- 冻结打包日志放在可执行文件与依赖目录的共同父目录下。

## 0.1.1 - 2026-08-29

- Fixed GUI/headless logging so task start, progress, source failures, tracebacks, fallback decisions, export failures, and final results are always written.
- Moved packaged Windows logs beside `StockAnalysis.exe` and `_internal` for portable troubleshooting while retaining user-directory config, cache, database, and raw responses.
- Added official Shanghai, Shenzhen, and Beijing exchange security-list fallback when the primary A-share list endpoint disconnects.
- Added GUI failure reasons, portable-log packaging smoke coverage, official-list live verification, and dynamic versioned archive names.

## 0.1.0 - 2026-08-28

- Added PySide6 GUI and shared headless pipeline for A-share/HK analysis.
- Added deterministic fixture mode, test mode, cancellation, progress reporting, JSON configuration recovery, SQLite cache, rotating logs, and raw-response audit storage.
- Added paginated A-share universe, official HKEX equity list, annual financials, quotes, IPO information, A-share block trades and capital flow adapters.
- Added HKD normalization with historical FX conversion when the source reports another currency.
- Added template-based 26-column Excel output with formulas, formatting, provenance, missing-data and run-information sheets.
- Added Windows onedir build/smoke scripts, macOS handoff scripts, automated tests, and bilingual documentation.
