# 容器运行

正式 Web 镜像由仓库根 Dockerfile 构建，docker/entrypoint.sh 调用 docker/db_init.py 后启动 app.backend.main:app，并提供构建好的前端静态文件。

旧 LangGraph CLI 专用的 Dockerfile、Compose、run.sh/run.bat 已随旧分析实现删除。不要用旧上游仓库的安装说明操作本项目。

本地 PostgreSQL 使用根目录 `compose.local.yml`，启动与配置见 [本地部署指南](../docs/LOCAL_DEPLOY.md)。用户管理及其他 SQL 表使用 PostgreSQL，MongoDB 仍是可选的行情缓存与历史存储。

当前部署流程与限制见 [部署说明](../docs/DEPLOY.md)。新架构部署需等待 [需求基线](../docs/requirements/market-data-and-analyze.md) 的实现与验收。
