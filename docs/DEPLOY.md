# 当前部署说明

本页描述仓库已有部署实现；MongoDB 与新 Analyze LangGraph 尚未部署。目标和验收见 [需求基线](requirements/market-data-and-analyze.md)。

本机安装和无 MongoDB 验收请使用 [本地部署指南](LOCAL_DEPLOY.md)，包括开发模式和由 FastAPI 托管构建后前端的方式。

## 运行结构

根 Dockerfile 构建前端与 Python 后端。docker/entrypoint.sh 在挂载卷上调用 docker/db_init.py，然后启动 uvicorn app.backend.main:app。

db_init.py 按数据库状态选择 ORM 初始化并 stamp，或执行现有 Alembic 增量迁移。已有数据库升级前必须备份；不要直接用 create_all 代替迁移。

fly.toml 当前记录 app=quantlab、region=nrt、同源前端与 API、遗留 /data 卷、单实例及 GET /health 健康检查。这是仓库配置，不是已核验的线上资源状态。部署前检查目标 app、卷和域名，禁止无意新建或覆盖项目。

应用 SQL 默认使用 PostgreSQL，通过 `DATABASE_URL` 配置。Fly 的硬编码 SQLite 地址已移除，发布前必须用平台 secrets 设置可连接的 PostgreSQL URL；本次只启动本地 Docker PostgreSQL，未修改线上数据库或迁移线上数据。遗留 SQLite 卷保留用于已有文件和备份。

## 配置与发布

- 构建时：VITE_API_URL；运行时：DATABASE_URL、FRONTEND_DIST、FRONTEND_ORIGINS、FRONTEND_BASE_URL。
- 鉴权/用户 key 加密：JWT_SECRET、APP_ENCRYPTION_KEY。开启生产保护前核实 ENVIRONMENT、REQUIRE_EMAIL_VERIFICATION、RATE_LIMIT_ENABLED。
- 邮件验证：按当前 auth 邮件实现配置 RESEND_API_KEY、RESEND_FROM_EMAIL。
- 默认使用 Yahoo 日线和 Finnhub 当前数据；Finnhub key 缺失/权限受限会反映为缺少对应证据。
- MongoDB 可选：MONGODB_URI、MONGODB_DATABASE、MONGODB_TIMEOUT_MS；不配置时继续在线分析。迁移命令与回滚边界见 development.md。正式服务端 schema 尚需独立验收。
- 不在 Git、日志或提示词中保存真实 key/URI；付费模型 key 必须显式注入，owner 不再有隐式 env fallback。Ollama 失败不切换付费供应商。

由已授权操作人检查配置和备份后执行 `fly deploy`。随后核对 /health、登录/验证、用户权限、Scanner 数据健康、Analyze、历史报告和日志；仅构建成功不等于端到端通过。

## 运维边界

SQL 已切换 PostgreSQL，仍因进程内 APScheduler 按单实例运行；仅增加 MongoDB 并不会自动解除这一限制。多实例需要独立的调度协调与并发验证。

容量、成本与快照保留期以部署平台实际账户为准，不沿用旧笔记中的估计。数据库升级和报告迁移均需独立的备份与回滚方案。
