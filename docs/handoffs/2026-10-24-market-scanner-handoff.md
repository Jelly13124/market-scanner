# Market Scanner 接手文档 — 2026-10-24

> 最新状态与无 MongoDB 验收见 [2026-10-25 本地验收交接](2026-10-25-local-validation.md)。下文为原始设计/接手快照，旧实现差距以新交接为准。


## 接手后更新：旧 LangGraph 已退役

用户已授权删除旧 LangGraph Analyze。现已删除 src/main.py、绑定旧图的回测 CLI 和专用 Docker 启动文件；Scanner 旧批量分析按钮移除，POST /pipeline/run 返回 410，不创建执行记录，旧 Pipeline cron 停用且拒绝重新启用。历史 Pipeline 查询、现有 run_sop Analyze、有效 agent/AgentState 和通用回测引擎保留。v2 Pipeline 与 workflow backtest 的离线注入适配器保留，默认实时执行明确报退役错误，不再导入旧图。

本次验证：已建立本地 Python 3.12 隔离环境（.venv，不入 Git）；Pipeline 路由、调度、注入适配器和 workflow backtest 离线测试共 39 项通过；全仓 Python 静态语法、旧图导入残留及 git diff --check 通过。前端未执行完整构建；未请求真实行情/模型、未部署。

下文为交接时基线；旧图仍存在和旧 Pipeline 可执行的描述已被此更新取代。新 Analyze 的 LangGraph 迁移仍待实现，其余入口的模型密钥隔离仍需验证。

## 先读这段

当前在**需求和数据库设计完成、业务实现未开始**的阶段。用户最新强调：**每日扫描必须保存到 MongoDB 历史，不只保存历史 K 线、分析报告或 Top N。** 本轮补上 scan_runs/scan_results 及来源关联。

正确工作目录：`/Users/jelly/Desktop/market-scanner`。聊天原 cwd 是 `/Users/jelly/Desktop/5400`，不要在那里误改别的项目。用户 Graphify 副本 `/Users/jelly/Desktop/bloger/实测/market-scanner` 只用于参考，不能当开发主目录。

GitHub：<https://github.com/Jelly13124/market-scanner>。默认分支 main，HEAD `99055518c2a94b8d99b95bf3a69e879b50e2acc8`（Initial commit）。此前按用户要求重建并推送了单提交历史；GitHub Contributors 缓存是否更新尚未确认。不要继续重写历史或删除仓库。

**当前有大量未提交改动**，包括用户要求的旧文档删除和本轮新设计。不要 reset/clean 或再次 clone 覆盖它们。需求/ERD/handoff 尚未提交、推送，提交前检查 git status。

## 确认的产品与技术决策

1. 行情免费：Finnhub 提供日内实时报价，Yahoo 提供历史日线。
2. Yahoo 历史、新闻、财报、公司快照和事件入 MongoDB；分析/回测读 MongoDB，不在节点里临时联网下载 Yahoo。
3. v1 不建 Mongo 实时 quote/tick 集合，只做短期内存缓存。扫描时真正用于判断的报价可以作为单次证据保存，不能误变成逐笔归档。
4. **每日和手动扫描保存完整批次与各标的 outcome**：当次 universe/config/as_of/versions、Top N 与未入选、无事件、缺数据、失败、detector 分量以及输入证据版本。同日主动重扫独立记录，调度重试幂等。
5. 新 Analyze 为主入口，必须迁到 LangGraph，保留有效旧 agent/计算。辩论从一次模型模拟改为有界独立节点。逐步下线重复旧入口。
6. 删除 EODHD 全链路：实现/导出/工厂/CLI/密钥入口/tier 标记/专属测试。FD 不再是新主线必要依赖；其完整下线是独立兼容迁移，不能未经检查一并删掉。
7. 模型仍支持 BYOK / Ollama，不要求全程免费。不得隐式消耗主机付费模型 key；Ollama 失败不能自动切到付费模型。
8. 报告存 MongoDB，可回看、精确复用、强制重跑；私有请求、报告和缓存按用户隔离。
9. SQL 暂保留账户/key/权限/watchlist/配置/调度/交易。旧报告和扫描历史幂等迁移，验证并保留回滚窗口后才考虑旧表退役。
10. 用户明确要求删除所有仓库旧计划和实测笔记；保留有效运行说明、工程约束和运行时提示词。

## 文档入口（当前事实来源）

- [确认需求](../requirements/market-data-and-analyze.md)：包含 MD-04 每日扫描历史。
- [完整全字段 ERD](../design/mongodb-full-erd.md) / [Mermaid 源码](../design/mongodb-full-erd.mmd)。
- [数据模型说明](../design/mongodb-market-data-erd.md)：第 10 节专门描述每日扫描历史。
- [字段字典](../design/mongodb-data-dictionary.md) / [物理定义 JSON](../design/mongodb-schema.json)。
- [开发说明](../development.md) / [部署说明](../DEPLOY.md)。

物理定义现为 v2.2，**13 个 MongoDB 普通集合**：instruments、price_bars、news_articles、financial_statements、company_snapshots、corporate_events、data_sync_jobs、datasets、analysis_runs、reports、llm_cache、scan_runs、scan_results。SQL_USERS 只在 ERD 显示逻辑账户引用，不新建 Mongo 集合。LangGraph checkpoint 用所选兼容插件独立集合，尚未确定内部 schema。

PK 为 _id；业务 UK 是命名复合/条件索引；FK 跨集合和 SQL↔Mongo 都由应用检查。validator 只覆盖已定义的结构/条件，payload subtype、归属、状态机和时点可得性仍需领域模型验证。JSON 目前只是设计，没有执行建库。

## 已完成

- 审查了数据源、Web/后台扫描、旧 LangGraph、Analyze SOP、密钥路径和可疑死代码。
- 删除 48 份 docs/superpowers 历史文档和 6 份根目录计划/实测笔记，共 54 份。
- 更新 README/子目录 README、CLAUDE.md、部署开发说明及若干过时注释/docstring。研究 prompts 保留。
- 写需求、ERD、字段字典和物理索引/validator 定义，并补上每日全量扫描历史。
- Finnhub 官方核验：stock-candles 文档内嵌 window.docSchema 中 /stock/candle 的 premium='Premium Access Required'；company-news 的 freeTier='1 year of historical news and new updates'，端点说明北美公司。没有使用用户 key 实测，不承诺无限/任意多年新闻回填。
- 用户 Graphify 报告只用于依赖定位；图谱副本与本地原代码 tree SHA 相同，路径推断/零入度不直接当死代码证据。

## 尚未实现及审查发现

### 必须优先处理

- 当前 /pipeline/run 允许普通用户触发，但旧调用链未传用户模型 keys，src/utils/llm.py → get_model 默认允许 host env fallback。有意外付费风险。
- 当前 free hybrid 仍把历史价格指向 Finnhub /stock/candle，403 会转空结果；现有 YFinanceClient.get_prices 直接 NotImplementedError。
- Scanner CLI 默认 hybrid 仍强制 EODHD key；EODHD 代码完全没有被删除，仅注释/文档清理。
- 当前 Analyzer run_sop 使用手写流程和 ThreadPoolExecutor；src/main.py 的旧流程才是 StateGraph。
- 旧 agent 原地修改 nested analyst_signals，reducer 是浅合并。并发风险尚未在固定 LangGraph 版本运行复现，别把它描述为已确认线上丢信号。
- 财务当前快照被标成请求历史日期；TTM 适配用年度报表。修正时保留 point-in-time 限制，不用免费快照伪造历史基本面。
- 当前 scanner_service 调用 run_scan(top_n=...)，并仅把返回 scored 项写 SQL watchlist_entries。**要保存完整扫描 outcome，必须改 runner 输出/observer/repository 契约，不能只把 SQL Top N 复制到 Mongo。**

### 主要代码位置

- `app/backend/services/scanner_service.py`：扫描执行、Top N 持久化、后续 SOP。
- `v2/scanner/runner.py` / `models.py` / `detectors/`：扫描输出和 detector 状态。
- `app/backend/database/models.py`：旧 ScanRun/WatchlistEntry/ResearchReport。
- `src/research/sop_orchestrator.py` / `sections/` / `modules/debate.py`：当前 Analyze 与单调用辩论。
- `src/main.py` / `src/graph/state.py` / `src/utils/llm.py`：旧图与状态/模型调用。
- `v2/data/` / `src/tools/api.py` / `src/tools/line_items.py`：数据路由与旧兼容层。
- `app/backend/routes/pipeline.py` / `research.py` / `services/scheduler_service.py`：用户/后台费用隔离及执行入口。

## 推荐接手顺序

1. 保护未提交文档；读需求和第 10 节扫描历史，评审 schema/索引及状态机。
2. 建 Python >=3.11 隔离环境；锁定 MongoDB、PyMongo、LangGraph/checkpointer 兼容版本，拿到服务端连接配置。不要把 key/URI 写进 Git 或聊天。
3. 先堵普通用户的主机模型 key fallback，然后定义数据库 Repository 与领域校验。
4. 实现 Yahoo 历史入库、新闻/财报等证据同步，免费权限错误显式呈现；缺口 gate、幂等、修订与数据快照一起完成。
5. 改 Scanner 保留完整 universe 的 outcome，写 scan_runs/scan_results，保存配置/证据版本并验证发布屏障。新正常结果关联 dataset，旧迁移标 legacy_topn_only。
6. 切换 Finnhub+Mongo 路由，清除 EODHD；验证 Scanner/CLI/Lab/回测。分析节点不直接在线抓 Yahoo。
7. Analyze 迁 LangGraph，接 BYOK/Ollama、有界辩论、checkpoint 恢复、报告和节点缓存；分析保留 source_scan_result_id。
8. 幂等迁移旧 SQL 报告与扫描历史；核对 owner、数量/内容，不补造旧输入。完成回滚演练后再切读。
9. 先离线/故障测试，再小范围真实免费源 smoke，最后才部署。不要一上来全市场回填或触发模型计费任务。

## 环境与验证边界

系统 python3 在此前检查为 3.9.6，缺 pytest/pydantic/pandas/langgraph 等；项目要求 >=3.11。没有完成依赖安装、运行完整测试或创建 MongoDB。当前工具 gh 位于用户本地工具目录，已经完成 GitHub 登录；不要打印 token。

已做：Python 全仓静态语法检查；17 个修改源码相对 HEAD 去除 docstring 后 AST 等价；Markdown 链接、JSON、schema-required/index 字段、ERD 字段一致性、git diff --check。新增扫描模型需要再跑同类静态校验。

未做：MongoDB 上实际运行 validator/索引/事务；LangGraph/checkpointer 接通；真实行情/新闻 smoke；端到端测试；部署。文档中的索引定义不能当真实数据库验证通过。

保留原则：历史公开市场证据和新扫描批次默认不 TTL 清理；报告引用的输入版本不可删；模型缓存可 TTL 但读取时立即检查 expires_at；实时 quote 不进入这个持久化历史模型。
