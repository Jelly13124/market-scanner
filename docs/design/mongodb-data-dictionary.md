# MongoDB 字段字典与物理约束 v2.2

> v2.3 实现补充：MongoDB 可选，公共数据支持在线回退。company_snapshots.snapshot_kind 新增 provider_response；payload 保存精确 request_key、类型化响应及 expires_at（读取时判断过期，不删除历史）。关联索引见 mongodb-schema.json。LangGraph 的内部 checkpoint/writes 使用独立集合，不混入市场证据集合。服务端物理验证仍待验收。


来自 [物理定义](mongodb-schema.json)。设计稿，未执行。PK 为 _id；复合 UK 按整组字段唯一；optional 省略而非 null。条件文档约束以 validator 和 [设计说明](mongodb-market-data-erd.md) 为准。

## instruments

稳定标的身份与供应商代码映射

| 字段 | BSON 类型 | 必填 | 说明 |
|---|---|---|---|
| `_id` | objectId | 是 | PK；MongoDB 自动唯一索引 |
| `schema_version` | int | 是 | 文档 schema 版本 |
| `market` | string | 是 | 市场，如 US/CN |
| `exchange` | string | 是 | 交易所 MIC；不使用任意展示名 |
| `symbol` | string | 是 | 规范代码，不充当永久主键 |
| `name` | string | 是 | 名称 |
| `asset_type` | string | 是 | 资产类型；equity, etf, index |
| `currency` | string | 是 | ISO 4217 币种 |
| `timezone` | string | 是 | IANA 时区 |
| `provider_symbols` | object | 是 | yahoo/finnhub 的代码映射 |
| `symbol_history` | array | 否 | 曾用代码及其有效范围 |
| `active` | bool | 是 | 是否仍有效 |
| `created_at` | date | 是 | UTC 创建时间 |

| 索引 | 字段 | 约束 |
|---|---|---|
| `_id_` | `_id:1` | PK / UNIQUE |
| `uq_active_instrument_symbol` | `{"market": 1, "exchange": 1, "symbol": 1}` | UK；partial={"active": true} |

引用：

## price_bars

Yahoo 日线历史，保存不可变修订版本

| 字段 | BSON 类型 | 必填 | 说明 |
|---|---|---|---|
| `_id` | objectId | 是 | PK；MongoDB 自动唯一索引 |
| `schema_version` | int | 是 | 文档 schema 版本 |
| `instrument_id` | objectId | 是 | FK instruments._id |
| `source` | string | 是 | 来源；yahoo |
| `interval` | string | 是 | 第一阶段仅日线；1d |
| `session_date` | string | 是 | 交易所本地 YYYY-MM-DD |
| `bar_time` | date | 是 | 该交易 session 开盘时间转 UTC |
| `revision` | int | 是 | 同一逻辑 bar 的版本，从 1 开始 |
| `open` | decimal | 是 | 原始开盘价 |
| `high` | decimal | 是 | 原始最高价 |
| `low` | decimal | 是 | 原始最低价 |
| `close` | decimal | 是 | 原始收盘价 |
| `volume` | long | 是 | 成交量 |
| `adjusted_close` | decimal | 否 | 供应商复权收盘价；缺失则省略 |
| `dividend` | decimal | 否 | 每股分红 |
| `split_ratio` | decimal | 否 | 拆股比例 |
| `adjustment_policy` | string | 是 | 原始价格及复权计算策略版本 |
| `content_hash` | string | 是 | 规范化内容 SHA256 |
| `fetched_at` | date | 是 | 本次抓取时间 |
| `first_seen_at` | date | 是 | 系统第一次见到该版本的时间 |

| 索引 | 字段 | 约束 |
|---|---|---|
| `_id_` | `_id:1` | PK / UNIQUE |
| `uq_bar_revision` | `{"instrument_id": 1, "source": 1, "interval": 1, "session_date": 1, "revision": -1}` | UK |
| `ix_bar_range` | `{"instrument_id": 1, "interval": 1, "bar_time": 1, "revision": -1}` | 查询索引 |

引用：`instrument_id` → `instruments._id`

## news_articles

新闻元数据与版本；一篇新闻可关联多个标的

| 字段 | BSON 类型 | 必填 | 说明 |
|---|---|---|---|
| `_id` | objectId | 是 | PK；MongoDB 自动唯一索引 |
| `schema_version` | int | 是 | 文档 schema 版本 |
| `article_key` | string | 是 | 稳定逻辑文章键：SHA256(provider+provider_article_id)，缺 ID 时用规范 URL |
| `revision` | int | 是 | 内容修订版本 |
| `provider` | string | 是 | API 数据来源，如 finnhub |
| `provider_article_id` | string | 否 | 供应商 article id，统一字符串 |
| `canonical_url` | string | 是 | 规范化原文 URL |
| `publisher` | string | 是 | 新闻原发布方 |
| `headline` | string | 是 | 标题 |
| `summary` | string | 是 | 供应商允许保存的摘要 |
| `language` | string | 是 | BCP47 语言代码 |
| `instrument_ids` | array | 是 | FK instruments._id；去重数组 |
| `published_at` | date | 是 | 供应商给出的发布时间 |
| `first_seen_at` | date | 是 | 本系统首次见到此版本 |
| `fetched_at` | date | 是 | 抓取时间 |
| `content_hash` | string | 是 | 标题/摘要等规范内容 hash |
| `content_policy` | string | 是 | 保存范围；metadata_summary, licensed_fulltext |
| `fulltext_file_id` | objectId | 否 | 有授权时的 GridFS 全文引用 |
| `quality` | object | 否 | 时间缺失、来源异常、覆盖范围提示 |

| 索引 | 字段 | 约束 |
|---|---|---|
| `_id_` | `_id:1` | PK / UNIQUE |
| `uq_article_revision` | `{"article_key": 1, "revision": -1}` | UK |
| `ix_news_instrument_time` | `{"instrument_ids": 1, "published_at": -1, "article_key": 1, "revision": -1}` | 查询索引 |

引用：`instrument_ids[]` → `instruments._id`；`fulltext_file_id` → `GridFS.files._id`

## financial_statements

财报披露与重述版本；保留报告期和可得时间

| 字段 | BSON 类型 | 必填 | 说明 |
|---|---|---|---|
| `_id` | objectId | 是 | PK；MongoDB 自动唯一索引 |
| `schema_version` | int | 是 | 文档 schema 版本 |
| `instrument_id` | objectId | 是 | FK instruments._id |
| `source` | string | 是 | 来源供应商 |
| `period_type` | string | 是 | 财报周期；annual, quarterly |
| `period_end` | date | 是 | 报告期结束日 |
| `filing_key` | string | 是 | 来源 filing id；无 ID 时用稳定的报告期/文件标识 |
| `revision` | int | 是 | 同一 filing 重述版本 |
| `published_at` | date | 否 | 真实披露时间；未知则省略 |
| `first_seen_at` | date | 是 | 本系统首次获知版本 |
| `currency` | string | 是 | 财报币种 |
| `income_statement` | object | 是 | 标准字段映射后的利润表，金额 Decimal128 |
| `balance_sheet` | object | 是 | 标准资产负债表，金额 Decimal128 |
| `cash_flow` | object | 是 | 标准现金流表，金额 Decimal128 |
| `source_url` | string | 否 | 披露/来源链接 |
| `content_hash` | string | 是 | 规范内容 SHA256 |
| `pit_status` | string | 是 | 时点可得性；verified_publication, observed_only, unknown_publication |

| 索引 | 字段 | 约束 |
|---|---|---|
| `_id_` | `_id:1` | PK / UNIQUE |
| `uq_filing_revision` | `{"instrument_id": 1, "source": 1, "filing_key": 1, "revision": -1}` | UK |
| `ix_financial_period` | `{"instrument_id": 1, "period_type": 1, "period_end": -1}` | 查询索引 |

引用：`instrument_id` → `instruments._id`

## company_snapshots

当前公司资料、指标、分析师目标价快照，不冒充历史财报

| 字段 | BSON 类型 | 必填 | 说明 |
|---|---|---|---|
| `_id` | objectId | 是 | PK；MongoDB 自动唯一索引 |
| `schema_version` | int | 是 | 文档 schema 版本 |
| `instrument_id` | objectId | 是 | FK instruments._id |
| `source` | string | 是 | 来源 |
| `snapshot_kind` | string | 是 | 快照类型；profile, metrics, analyst_targets |
| `observed_at` | date | 是 | 实际抓取观察时间 |
| `effective_at` | date | 否 | 来源声明的有效时间，无则省略 |
| `payload` | object | 是 | 按 snapshot_kind 校验的快照字段 |
| `content_hash` | string | 是 | 规范内容 SHA256 |
| `currency` | string | 否 | 货币字段的币种 |

| 索引 | 字段 | 约束 |
|---|---|---|
| `_id_` | `_id:1` | PK / UNIQUE |
| `uq_company_observation` | `{"instrument_id": 1, "source": 1, "snapshot_kind": 1, "observed_at": 1}` | UK |
| `ix_company_snapshot_history` | `{"instrument_id": 1, "snapshot_kind": 1, "observed_at": -1}` | 查询索引 |

引用：`instrument_id` → `instruments._id`

## corporate_events

财报日历、内部人交易、评级变动、分红拆股等时间化事件

| 字段 | BSON 类型 | 必填 | 说明 |
|---|---|---|---|
| `_id` | objectId | 是 | PK；MongoDB 自动唯一索引 |
| `schema_version` | int | 是 | 文档 schema 版本 |
| `instrument_id` | objectId | 是 | FK instruments._id |
| `source` | string | 是 | 来源 |
| `event_key` | string | 是 | 供应商事件 ID 或类型定义的稳定自然键 |
| `event_type` | string | 是 | 事件类型；earnings_calendar, earnings_result, insider_trade, analyst_rating, dividend, split |
| `revision` | int | 是 | 更新/取消版本 |
| `event_at` | date | 是 | 事件发生时间或计划发生时间 |
| `published_at` | date | 否 | 该事件信息首次发布的时间，未知省略 |
| `first_seen_at` | date | 是 | 本系统首次看到该版本 |
| `status` | string | 是 | 状态；scheduled, confirmed, cancelled |
| `payload` | object | 是 | 按事件类型定义的业务字段 |
| `content_hash` | string | 是 | 规范内容 SHA256 |

| 索引 | 字段 | 约束 |
|---|---|---|
| `_id_` | `_id:1` | PK / UNIQUE |
| `uq_event_revision` | `{"instrument_id": 1, "source": 1, "event_type": 1, "event_key": 1, "revision": -1}` | UK |
| `ix_event_instrument_time` | `{"instrument_id": 1, "event_type": 1, "event_at": -1}` | 查询索引 |

引用：`instrument_id` → `instruments._id`

## data_sync_jobs

后台同步记录：历史价格/新闻/财报；不采集日内实时 tick

| 字段 | BSON 类型 | 必填 | 说明 |
|---|---|---|---|
| `_id` | objectId | 是 | PK；MongoDB 自动唯一索引 |
| `schema_version` | int | 是 | 文档 schema 版本 |
| `resource_type` | string | 是 | 同步资源；price_bars, news_articles, financial_statements, company_snapshots, corporate_events |
| `instrument_id` | objectId | 是 | FK instruments._id |
| `source` | string | 是 | 来源 |
| `range_start` | date | 是 | 查询范围起始（包含） |
| `range_end` | date | 是 | 查询范围结束（不包含） |
| `status` | string | 是 | 任务状态；queued, running, succeeded, partial, failed, cancelled |
| `attempt` | int | 是 | 尝试次数 |
| `request_key` | string | 是 | 稳定请求指纹 |
| `active_job_key` | string | 否 | 仅 queued/running 存在 |
| `cursor` | object | 否 | 供应商分页位置/断点 |
| `coverage` | object | 是 | 价格缺口或分页/窗口完成信息 |
| `lease_owner` | string | 否 | worker 标识 |
| `lease_until` | date | 否 | 租约截止 |
| `created_at` | date | 是 | 创建时间 |
| `finished_at` | date | 否 | 结束时间 |
| `error` | object | 否 | 安全错误码/摘要，禁止含 key |

| 索引 | 字段 | 约束 |
|---|---|---|
| `_id_` | `_id:1` | PK / UNIQUE |
| `uq_active_sync` | `{"active_job_key": 1}` | UK；partial={"active_job_key": {"$type": "string"}} |
| `ix_sync_pickup` | `{"status": 1, "lease_until": 1, "created_at": 1}` | 查询索引 |
| `ix_sync_coverage` | `{"instrument_id": 1, "resource_type": 1, "range_start": 1, "range_end": 1}` | 查询索引 |

引用：`instrument_id` → `instruments._id`

## datasets

分析证据快照：固定每份报告使用的数据版本

| 字段 | BSON 类型 | 必填 | 说明 |
|---|---|---|---|
| `_id` | objectId | 是 | PK；MongoDB 自动唯一索引 |
| `schema_version` | int | 是 | 文档 schema 版本 |
| `owner_id` | string | 是 | 逻辑 FK SQL users.id；字符串规范化 |
| `instrument_id` | objectId | 是 | 主分析标的 FK |
| `as_of` | date | 是 | 分析截止时间 |
| `knowledge_mode` | string | 是 | 时间可得性模式；live_observed, historical_pit, retrospective |
| `dataset_hash` | string | 是 | 实际输入/源版本/特征计算版本的 hash |
| `manifest` | array | 否 | 固定版本文档引用；与 manifest_file_id 二选一 |
| `manifest_file_id` | objectId | 否 | 超大 manifest 的 GridFS 引用 |
| `manifest_file_hash` | string | 否 | GridFS manifest 的 SHA256 |
| `features` | object | 是 | 给模型的紧凑指标/证据摘要，包含版本标识 |
| `quality` | object | 是 | 缺失、迟到、数据权限与覆盖缺口 |
| `created_at` | date | 是 | 冻结时间 |
| `expires_at` | date | 否 | 未关联报告时允许清理的候选时间 |

| 索引 | 字段 | 约束 |
|---|---|---|
| `_id_` | `_id:1` | PK / UNIQUE |
| `uq_owner_dataset` | `{"owner_id": 1, "dataset_hash": 1}` | UK |
| `ix_dataset_lookup` | `{"owner_id": 1, "instrument_id": 1, "as_of": -1}` | 查询索引 |

引用：`owner_id` → `SQL.users.id`；`instrument_id` → `instruments._id`；`manifest[].document_id` → `manifest[].collection._id`；`manifest_file_id` → `GridFS.files._id`

## analysis_runs

一次 LangGraph 分析的执行记录，而非市场数据或报告正文

| 字段 | BSON 类型 | 必填 | 说明 |
|---|---|---|---|
| `_id` | objectId | 是 | PK；MongoDB 自动唯一索引 |
| `schema_version` | int | 是 | 文档 schema 版本 |
| `owner_id` | string | 是 | 逻辑 FK SQL.users.id |
| `instrument_id` | objectId | 是 | FK instruments._id |
| `dataset_id` | objectId | 否 | FK datasets._id；准备数据期间可缺失 |
| `request` | object | 是 | 持仓/预算/风险/语言/章节/persona/轮数等规范输入 |
| `run_key` | string | 是 | 完整输入和版本指纹；允许多次强制执行 |
| `active_run_key` | string | 否 | 仅非终态设置，用于请求合并 |
| `thread_id` | string | 是 | 服务端生成的 LangGraph 执行 ID |
| `versions` | object | 是 | graph/prompt/model/provider/schema/feature 版本 |
| `status` | string | 是 | 状态；queued, waiting_data, running, succeeded, partial, failed, cancelled |
| `usage` | object | 是 | 实际请求数/token/费用与缓存命中 |
| `created_at` | date | 是 | 创建时间 |
| `finished_at` | date | 否 | 结束时间 |
| `error` | object | 否 | 失败节点和安全错误摘要 |
| `cached_from_report_id` | objectId | 否 | 直接复用历史报告时的来源 |
| `source_scan_result_id` | objectId | 否 | 由扫描触发时引用 scan_results._id；独立分析省略 |

| 索引 | 字段 | 约束 |
|---|---|---|
| `_id_` | `_id:1` | PK / UNIQUE |
| `uq_analysis_thread` | `{"thread_id": 1}` | UK |
| `uq_active_analysis` | `{"active_run_key": 1}` | UK；partial={"active_run_key": {"$type": "string"}} |
| `ix_owner_runs` | `{"owner_id": 1, "instrument_id": 1, "created_at": -1}` | 查询索引 |
| `ix_run_reuse` | `{"owner_id": 1, "run_key": 1, "status": 1}` | 查询索引 |

引用：`owner_id` → `SQL.users.id`；`instrument_id` → `instruments._id`；`dataset_id` → `datasets._id`；`cached_from_report_id` → `reports._id`；`source_scan_result_id` → `scan_results._id`

## reports

最终报告档案，不与运行记录或行情混存

| 字段 | BSON 类型 | 必填 | 说明 |
|---|---|---|---|
| `_id` | objectId | 是 | PK；MongoDB 自动唯一索引 |
| `schema_version` | int | 是 | 文档 schema 版本 |
| `owner_id` | string | 是 | 逻辑 FK SQL.users.id |
| `instrument_id` | objectId | 是 | FK instruments._id |
| `run_id` | objectId | 否 | 新报告必填；迁移报告可以缺失 |
| `dataset_id` | objectId | 否 | 新报告必填；迁移报告可以缺失 |
| `provenance` | string | 是 | 来源；native, legacy_unverified |
| `legacy_sql_id` | string | 否 | 迁移旧报告稳定 ID |
| `request_hash` | string | 是 | 规范分析请求 hash |
| `language` | string | 是 | 语言 |
| `summary` | string | 是 | 简短结论 |
| `sections` | object | 是 | 有界章节：markdown/structured/persona/status/evidence refs |
| `trade_plan` | object | 否 | 策略输出，缺失可省略 |
| `backtest` | object | 否 | 回测输出与数据限制，缺失可省略 |
| `artifacts` | array | 是 | HTML/图表/超大章节 GridFS 引用 |
| `versions` | object | 是 | graph/prompt/model/schema/renderer 版本 |
| `created_at` | date | 是 | 原始生成时间，不改成迁移时间 |
| `migrated_at` | date | 否 | 旧报告迁移时间 |

| 索引 | 字段 | 约束 |
|---|---|---|
| `_id_` | `_id:1` | PK / UNIQUE |
| `uq_native_report_run` | `{"run_id": 1}` | UK；partial={"run_id": {"$type": "objectId"}} |
| `uq_legacy_report` | `{"legacy_sql_id": 1}` | UK；partial={"legacy_sql_id": {"$type": "string"}} |
| `ix_owner_reports` | `{"owner_id": 1, "instrument_id": 1, "created_at": -1}` | 查询索引 |

引用：`owner_id` → `SQL.users.id`；`instrument_id` → `instruments._id`；`run_id` → `analysis_runs._id`；`dataset_id` → `datasets._id`

## llm_cache

成功节点模型结果缓存；不可替代报告档案

| 字段 | BSON 类型 | 必填 | 说明 |
|---|---|---|---|
| `_id` | objectId | 是 | PK；MongoDB 自动唯一索引 |
| `schema_version` | int | 是 | 文档 schema 版本 |
| `owner_id` | string | 是 | 缓存隔离范围 |
| `cache_key` | string | 是 | 节点实际输入+语言+模型参数+prompt/schema 版本 hash |
| `origin_run_id` | objectId | 是 | 首次生成结果的 run |
| `node_name` | string | 是 | 图节点名 |
| `input_hash` | string | 是 | 实际输入指纹 |
| `versions` | object | 是 | 模型/提示词/输出结构版本 |
| `output` | object | 是 | 结构校验通过的节点结果 |
| `usage` | object | 是 | 原始调用 token 与费用 |
| `created_at` | date | 是 | 创建时间 |
| `expires_at` | date | 是 | 逻辑过期时间 |

| 索引 | 字段 | 约束 |
|---|---|---|
| `_id_` | `_id:1` | PK / UNIQUE |
| `uq_owner_node_cache` | `{"owner_id": 1, "cache_key": 1}` | UK |
| `ttl_llm_cache` | `{"expires_at": 1}` | 查询索引；TTL=0 |

引用：`owner_id` → `SQL.users.id`；`origin_run_id` → `analysis_runs._id`

## scan_runs

每日/手动扫描批次历史；保留配置和实际 universe 快照

| 字段 | BSON 类型 | 必填 | 说明 |
|---|---|---|---|
| `_id` | objectId | 是 | PK |
| `schema_version` | int | 是 | schema 版本 |
| `owner_id` | string | 是 | SQL users.id；当前配置所属用户 |
| `execution_key` | string | 是 | 幂等键：调度槽位+owner+config revision；手动执行使用新 UUID |
| `legacy_sql_id` | string | 否 | 旧 scan_runs id，迁移才有 |
| `config_id` | string | 是 | SQL scanner_configs.id 的逻辑引用 |
| `config_snapshot` | object | 是 | 当次参数、权重、Top N、启用 detector 与版本，不只引用可变配置 |
| `scan_date` | string | 是 | 市场本地扫描交易日 |
| `market` | string | 是 | 市场 |
| `timezone` | string | 是 | 用于日界和调度的 IANA 时区 |
| `trigger_type` | string | 是 | 触发方式；scheduled, manual, migration |
| `as_of` | date | 是 | 本次数据截止时间 UTC |
| `status` | string | 是 | 批次状态；queued, running, succeeded, partial, failed, cancelled |
| `universe_manifest` | array | 否 | 实际参与标的 ID 快照，必要时外置 |
| `universe_file_id` | objectId | 否 | 大 universe 的 GridFS 清单，与内嵌清单二选一 |
| `universe_hash` | string | 是 | 实际 universe 有序规范化 hash |
| `coverage_mode` | string | 是 | 历史完整性；full_universe, legacy_topn_only |
| `expected_count` | int | 是 | 预期标的数量 |
| `counts` | object | 是 | attempted/selected/no_event/no_data/error 等计数 |
| `versions` | object | 是 | scanner/scoring/detector/feature/schema 版本 |
| `attempt` | int | 是 | 崩溃恢复次数 |
| `created_at` | date | 是 | 创建时间 |
| `finished_at` | date | 否 | 完成时间 |
| `error` | object | 否 | 安全失败摘要，不含凭据 |

| 索引 | 字段 | 约束 |
|---|---|---|
| `_id_` | `_id:1` | PK / UNIQUE |
| `uq_scan_execution` | `{"execution_key": 1}` | UK |
| `uq_legacy_scan` | `{"legacy_sql_id": 1}` | UK；partial={"legacy_sql_id": {"$type": "string"}} |
| `ix_owner_scan_date` | `{"owner_id": 1, "scan_date": -1, "created_at": -1}` | 查询索引 |
| `ix_scan_status` | `{"status": 1, "created_at": 1}` | 查询索引 |

引用：`owner_id` → `SQL.users.id`；`config_id` → `SQL.scanner_configs.id`；`universe_manifest[]` → `instruments._id`；`universe_file_id` → `GridFS.files._id`

## scan_results

每个扫描标的的历史结果；不只保存 Top N，包含无事件、缺数据和失败

| 字段 | BSON 类型 | 必填 | 说明 |
|---|---|---|---|
| `_id` | objectId | 是 | PK |
| `schema_version` | int | 是 | schema 版本 |
| `scan_run_id` | objectId | 是 | FK scan_runs._id |
| `instrument_id` | objectId | 是 | FK instruments._id |
| `dataset_id` | objectId | 否 | 本次扫描使用的固定输入证据版本；旧迁移可缺失 |
| `owner_id` | string | 是 | 继承扫描批次 owner，查询隔离 |
| `outcome` | string | 是 | 区分完成/无数据/异常；evaluated, no_data, error, cancelled |
| `selected` | bool | 是 | 是否被当次 Top N 选中；不等于触发事件 |
| `rank` | int | 否 | 可评估候选中的排名，无排名则省略 |
| `composite_score` | double | 否 | 成功评分后才存在 |
| `event_score` | double | 否 | 事件分数 |
| `quant_score` | double | 否 | 量化分数；未算则省略 |
| `event_severity` | double | 否 | 截断前严重度 |
| `direction` | string | 否 | 方向；bullish, bearish, neutral |
| `detector_results` | array | 是 | 每个启用检测器的结果和版本，包括未触发与缺数据 |
| `quality` | object | 是 | 覆盖缺口、来源权限和部分结果标记 |
| `created_at` | date | 是 | 结果保存时间 |

| 索引 | 字段 | 约束 |
|---|---|---|
| `_id_` | `_id:1` | PK / UNIQUE |
| `uq_scan_instrument` | `{"scan_run_id": 1, "instrument_id": 1}` | UK |
| `ix_scan_selected_rank` | `{"scan_run_id": 1, "selected": 1, "rank": 1}` | 查询索引 |
| `ix_instrument_scan_history` | `{"owner_id": 1, "instrument_id": 1, "created_at": -1}` | 查询索引 |

引用：`scan_run_id` → `scan_runs._id`；`instrument_id` → `instruments._id`；`dataset_id` → `datasets._id`；`owner_id` → `SQL.users.id`

