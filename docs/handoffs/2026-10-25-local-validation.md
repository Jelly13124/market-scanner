# 本地验收交接 — 2026-10-25

## 最新用户决策

MongoDB 是可选的优先缓存和历史存储，不是分析的必需依赖。无记录、覆盖不足、未配置或连接失败时，统一数据层可以在线读取 Yahoo/Finnhub；缓存/历史未保存必须明确呈现。用户的 Docker MongoDB 据其说明正在运行且应为空，本轮按要求不连接、不安装 schema、不写入、不迁移它，先验证无 MongoDB 路径。

本页优先于 2026-10-24 交接快照中的旧实现描述；需求和 schema 的修订见 v2.3。

## 已落地

- 默认 hybrid：MongoDB 有效响应/日线缓存优先；在线回退 Yahoo 日线、Finnhub 当前数据。Yahoo 保留原始 OHLC、独立复权价、分红与拆股；日期适配保留旧调用方的 inclusive end。
- MongoStore 延迟连接、短超时、故障熔断和脱敏错误；未配置不会创建 MongoClient。13 个业务集合沿用设计，company_snapshots 新增 provider_response；checkpoint/writes 为独立内部集合。
- 公共原始响应、日线修订、新闻、事件和财报入库；记录同步覆盖账本。未验证的发布时点不冒充 PIT；历史请求不使用当前 Finnhub 财务快照，Yahoo TTM 由四个连续季度流量求和。
- Scanner 输出完整 universe outcome，包含未入选、no_event/no_data/error/retired。Mongo 批次冻结配置、版本、输入和排名，完成计数后才发布。SQL 继续保留 Top N 兼容结果；Mongo 失效时明确标注未保存，完全无数据不冒充无机会。
- Analyze 已迁 LangGraph：基础章节并行、依赖显式汇合、策略/证据/摘要在上游之后；独立、有界的发言与裁决节点替代一次模型模拟整段辩论。
- 可选 Mongo 报告、精确复用、用户隔离的节点缓存、force_rerun、checkpoint 与 owner/版本/dataset 校验后的 resume_run_id；HTML/大章节通过 GridFS artifact 存储。checkpoint 只用固定类型的 JSON 序列化，不包含模型 key。
- 所有付费模型默认不读取 host key；owner 也必须显式配置。Ollama 无 key 路径保留，不切换付费供应商；模型调用/缓存命中/token/失败与费用不确定状态分别记录。
- US watchlist 报价改为 Finnhub + 有界短期内存缓存，保留来源时间和接收时间，不建 tick 集合；保留 A 股旧报价路径。扫描按钮不再要求模型 key，Analyze readiness 支持所选 BYOK/Ollama。
- EODHD 实现、工厂/导出/CLI/探测脚本/专属测试和付费 tier 徽标已删除。FD 显式旧兼容入口保留。
- 旧 LangGraph 和批量 Pipeline 执行退役；旧全局 research cron 也已停用。旧记录查询和限 owner 的 legacy research 兼容入口保留，新报告调度使用 run_sop。
- SQL→Mongo 迁移工具默认预览，按 legacy_sql_id 幂等；旧 Top N 标 legacy_topn_only，不补造 universe/dataset；原 SQL 保留。未对用户数据库执行迁移。

## 本地验证边界

- `python -m scripts.smoke_no_mongo` 在临时 SQL 库上启动实际 FastAPI 生命周期并读取真实 Yahoo 数据：health 200、Analyze 200、SQL 保存 1 份报告、旧 Pipeline 410、MongoDB 未连接、模型调用 0。报告只选择 data_health/missing_data，不宣称通过了真实 AI 质量验收。
- SPY 2024-01-02 至 2024-01-05 的无 Mongo 在线回退实际返回 4 根日线。
- MongoDB 测试使用进程内 mongomock，覆盖命中/过期/故障、原始日线覆盖、修订、完整扫描发布、owner 隔离、报告复用/强制重跑、checkpoint 恢复和旧 SQL 迁移幂等；不连接 Docker。
- 前端 TypeScript 和 Vite 生产构建通过；构建仍有原有字体路径、Browserslist 和 bundle 大小提示。
- Python 环境为本地 .venv，Python 3.12；依赖锁文件已更新，Poetry check --lock 通过。工作环境/测试库/依赖目录不入 Git。
- 最终离线/故障/鉴权回归：1110 passed、2 skipped；随后费用元数据/Analyze 路由定向回归 16 passed。`git diff --check`、全仓 Python 静态语法检查及 Poetry 锁文件检查通过。

## 下一步（不把目标当成已验收）

1. 当前没有运行中的本地 Ollama；尚未实际调用 BYOK/Ollama 生成完整 AI 报告。后续选择明确配置的模型做小范围验收，不能拿 host key 自动代跑。
2. 无 Mongo 本地验收之后，再使用用户 Docker 的测试数据库应用 schema，验证真实 validator/索引、GridFS、故障和恢复、owner 查询及迁移/回滚。当前 mongomock 通过不等于这些服务端验证完成。
3. 当前证据同步主要是同步读穿缓存和覆盖账本；独立后台缺口任务、跨进程租约/fencing 与完整多 worker 接管仍需后续实现和验证。现有调度/SQL 仍按单实例运行。
4. CLI 的旧 Top N 返回契约保留；API/每日扫描通过 observer 保存全量 outcome。不要把未提供 owner/config 的独立 CLI 调用宣称为已保存完整私有批次。
5. MongoDB 关闭时可分析并保存 SQL 报告/Top N，但不承诺不存在的 Mongo 全量历史、跨进程 checkpoint 或节点缓存持久化；界面/API 会标明存储状态。
