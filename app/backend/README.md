# Market Scanner 后端

FastAPI 入口为 app.backend.main:app，路由注册在 routes/__init__.py。主要路由族包括 /health、/auth、/scanner、/pipeline、/research、/lab、/screener、/watchlists、/paper 和 /api-keys。实际参数和可用接口以 FastAPI OpenAPI 与当前 routes 为准，不沿用已删除的 /hedge-fund/run 说明。

当前数据库由 SQLAlchemy/Alembic 管理。docker/db_init.py 根据已有 schema 选择初始化或增量迁移；不要假设迁移链可以独立创建所有空库表。

Analyze 的 run_sop 已使用 LangGraph，MongoDB 是可选缓存/历史存储。旧 /research/run 限 owner，旧 LangGraph Pipeline 已退役（POST /pipeline/run 返回 410，定时任务停用）；不能将“用户自带 key”的目标视为全部路由已完成隔离。

安装与启动见 [根 README](../../README.md)，新架构与兼容迁移见 [需求基线](../../docs/requirements/market-data-and-analyze.md)。
