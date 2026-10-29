# main 代码复审 — 2026-10-29

审查基线：`main`，提交 `0e8d65b`。免登录实验已停止，未完成改动保存在独立 stash，没有合入 main。本次只审查，不修改业务实现。前端已重新构建为 main 的版本。

## 修复状态

以下 R1–R7 已按本轮指令修复，描述保留为修复前证据。R1/R2/R5/R6 优先完成：请求 schema 与 UI 拒绝空章节、刷新接入登录和限流、PATCH 显式 null 清空人物、调度保存配置快照。R3/R4/R7 随后完成：下一有效交易日开盘成交、交易 pnl 计入双边费用、OOS 基准按相同区间比较。

新增迁移 `d7e3f901b625`，旧调度保留 null 快照和默认行为，不覆盖历史结果。旧回测记录需重新运行才能采用修正后的执行逻辑。

## 已确认问题

### R1 · P1 · 零章节请求意外执行全量分析

位置：`app/backend/routes/research.py:271–274`。

`set(req.included_sections) if req.included_sections else set(SECTION_ORDER)` 把显式 `[]` 当成未提供。页面关闭全部章节后请求仍能变成 20 章节报告，可能消耗用户原本没选择的模型调用。

隔离复现：`AnalyzeRunRequest(ticker='AAPL', included_sections=[])` 经 `_to_analyze_request` 后章节数为 20。未调用模型。

建议：仅 `None` 使用默认章节；显式空列表拒绝运行，并让前端禁用对应 Run 按钮。这是输入契约修正，无需额外兜底层。

### R2 · P1 · 匿名请求可启动共享全市场快照抓取

位置：`app/backend/routes/screener.py:151–164`。

`POST /screener/snapshot/refresh` 没有登录依赖或重型任务限流，直接调用后台构建器。匿名访问者可以持续触发行情抓取和共享数据写入；进程内并发锁只能防重叠，不能防连续占用资源。

隔离复现：替换构建器，未携带 Authorization 的 POST 返回 200，构建器调用一次。没有发起实际全市场抓取。

建议：增加现有登录依赖与现有重型接口限流，保留并发锁，不必改变公开行情 GET。

### R3 · P1 · 回测使用信号当日收盘成交，违背次日开盘执行约定

位置：`src/lab/engine/simulation.py:99–107, 118–145`。

模拟器根据当前日收盘价和指标确定信号，随后立即按同一收盘价成交。模块文档声明在 next-day open 成交，实际没有待执行信号队列，也没有读取下一交易日 open。依赖收盘数据才能确认的突破、均线或 RSI 信号会获得不可按约定实现的成交价格，结果可能偏乐观。

合成行情复现：1 月 2 日收盘 100，次交易日开盘 120，信号在 1 月 2 日触发；记录却在 1 月 2 日按 100 买入。

建议：明确执行契约，收盘信号在下一有效交易日开盘成交，窗口最后一天的未执行信号不成交，并在成交时计费。

### R4 · P2 · 交易盈亏漏算买入成本，胜率与总资产可能互相矛盾

位置：`src/lab/engine/simulation.py:100–107, 141–144`；`src/lab/engine/metrics.py:74–83`。

现金在买入和卖出时均扣成本，但 `Trade.pnl` 只扣卖出成本。胜率和 profit factor 依赖这个 pnl，因此实际亏损交易可能被记成盈利。

合成行情复现：初始现金 10000，50 股按 100 买入、101.5 卖出，单边手续费 100 bps、滑点为零。买入成本 50、卖出成本 50.75；账户净亏 25.75，交易记录却盈利 24.25。

建议：持仓保留买入费用，平仓 pnl 扣除双边费用，使交易统计与现金变化一致。

### R5 · P2 · 清空人物覆盖后保存，旧人物配置仍会回来

位置：`app/frontend/src/components/panels/analyze/flow-list.tsx:97–103`；`app/backend/routes/analyze_flows.py:95–103`；`app/backend/repositories/analyze_flow_repository.py:110–113`。

前端清空时发送 `persona_overrides: null`；仓储把 None 当“不更新”，路由没有传入已有的 `clear_overrides` 参数。

隔离 API 复现：先保存 valuation=buffett，再 PATCH null；响应 200，返回值仍含 buffett。

建议：依据请求的 `model_fields_set` 区分“没提供字段”和“明确清空”，接通现有 clear 参数。

### R6 · P2 · Analyze 调度丢失当前流程与市场

位置：`app/frontend/src/components/panels/analyze/schedule-ticker-dialog.tsx:54–58`；`app/backend/services/scheduler_service.py:524–534`。

调度只保存股票、cron 和语言；后台重建默认请求，`use_personas=False`，市场默认 US。当前画布的章节、人物、轮数、市场与预算等均未继承。用户不能把这个按钮理解为定时执行当前画布；CN 股票还可能被错误路由到 US。

代码与请求 schema 复核确认，未实际创建定时任务或发送邮件。

建议：保存流程快照并贯穿参数；若暂不支持，入口明确标注只运行默认报告，并限制不支持的市场。

### R7 · P2 · OOS 策略与全区间基准比较，跑赢结论不可靠

位置：`src/lab/backtest_runner.py:124–130`；`src/lab/engine/verdict.py:60–73`。

策略 IS/OOS 分段计算，基准却用 start 到 end 的完整窗口；verdict 用 OOS CAGR 与全窗口 SPY CAGR 比较。当 IS 和 OOS 市场走势相差较大时，会错误判断跑赢或跑输。

调用链确认：`_compute_benchmark_cagr(start, end)` 的结果传入 `make_verdict(is_m, oos_m, ...)`，随后直接比较 `oos_m.cagr`。

建议：用于 OOS 判定的基准也只计算 midpoint 到 end，并尽量对齐有效交易日。

## 验证范围

- 隔离探针：`outputs/reviews/main_review_probe.py`（忽略的本地产物）。内存 SQL、虚构账号、受控后台构建器和两根合成日线；没有读取/修改真实用户记录，没有调用付费模型，也没有访问 MongoDB。
- 相关现有回归：99 passed（Analyze flow 路由/仓储、Backtest runner、owner guard、`tests/lab`）。测试通过不代表上述缺口不存在。
- TypeScript 与 Vite main 构建通过；仍有既有字体、Browserslist 和 bundle 大小提示。
- 未执行全量测试、生产部署或真实 AI 报告验收。本次复审不承诺覆盖全部模块与潜在问题。

建议优先处理 R1/R2/R3，再修 R4–R7。R1/R2/R5/R6 对应上一轮尚未修复的 F3/F2/F4/F7；R3/R4/R7 为本次新增确认。

## 修复后验收

- 相关主回归 211 passed，随后新增旧调度兼容与迁移测试，并运行调度测试 4 passed（其中 2 项与前一次重复）。
- TypeScript + Vite 构建通过。
- 真实本地 PostgreSQL 已备份并升级至 `d7e3f901b625`，后端已重启。
- 真实 API smoke 确认：匿名快照刷新 401、空章节 422、人物覆盖可清空、CN 调度快照中的章节/人物/轮数可保存并读回。临时账号和记录已清理；没有发送邮件、执行市场刷新或调用模型。
- 新回测测试覆盖下一有效开盘成交、末日信号不成交、缺失交易日、双边费用守恒和 OOS 基准区间。现存旧回测结果保留，不自动重算。
