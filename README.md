# Market Scanner / Quant Lab

股票事件扫描、研究报告、策略实验与模拟交易项目。后端为 Python/FastAPI，前端为 React/Vite。默认分支 `main`。

## 当前实现

- 默认行情链路：优先 MongoDB 有效缓存，缺失或不可用时回退 Yahoo 日线和 Finnhub 当前数据；MongoDB 不是启动或分析的必需依赖。
- Analyze 使用 LangChain 调用模型、LangGraph 编排流程，并行章节显式汇合后生成策略、证据和摘要；辩论按有界的独立发言与裁决节点执行。
- 投资人物保留 Buffett、Lynch、Wood、Burry、Druckenmiller 五位；每次辩论选两位。画布 Debate 节点支持自定义 1–5 轮，默认 1 轮；辩论模型调用数为 `2 × 轮数 + 1`（另有路由与报告章节调用），保存及加载流程会保留轮数和开关。
- 模型支持用户自带 key / Ollama；包括 owner 和后台任务在内，默认不使用主机付费 key。
- 扫描器输出完整 universe 的 detector outcome。启用 MongoDB 后保存完整扫描历史、冻结数据集、报告、节点缓存和 checkpoint；数据库不可用时继续在线执行并明确显示未保存。
- PostgreSQL 保存账户、配置、流程模板、调度、watchlist 和报告兼容副本；应用不再默认使用 SQLite。旧 LangGraph 执行入口和旧付费行情适配器已删除，FD 显式兼容入口保留。

本地验证与部署验收是不同阶段。MongoDB 的真实 validator/索引、生产迁移和真实模型报告仍需在对应环境验收；本轮先测试完全不连接 MongoDB 的路径。

详细契约见 [需求基线](docs/requirements/market-data-and-analyze.md)，字段关系见 [MongoDB ERD](docs/design/mongodb-market-data-erd.md)，当前工作记录见 [handoff](docs/handoffs/2026-10-28-postgres-local.md)。

## 功能入口

| 入口 | 当前能力 | 状态与边界 |
| --- | --- | --- |
| Watchlist / Screener / Scanner | 自选股、股票筛选、事件扫描 | 行情依赖网络与数据源权限 |
| Analyze / Reports | 组合预置分析模块、人物辩论、报告 | 需要可用模型；画布连线暂不改变执行顺序，不支持任意自定义 agent / 工具 |
| Backtest | 股票池、日期、规则、成本、样本内/外结果与图表 | **基础版**：无需模型 key；尚未连接 Analyze 策略，缺少进度、取消任务及参数对比 |
| Paper | 手动模拟账本原型，代码与已有数据保留 | **开发中，暂不开放**：入口不可点击，个人 Paper API 未挂载；尚无市场价格自动估值 |

独立 Sectors、Institutional 页面已移除，原 Lab 页面替换为 Backtest。Analyze、Backtest、Paper 目前是独立功能，尚未形成自动执行闭环。

## 数据库和登录

PostgreSQL（PG）是课程版的必需组件，保存账号、配置、流程、回测和个人模拟账户。MongoDB 只负责可选缓存与历史数据；关闭 MongoDB 不会关闭 PostgreSQL。

本地使用 Docker 运行 PostgreSQL，**不需要在系统手动安装 PostgreSQL 服务**。首次打开页面自行注册普通账户即可，目前没有预设管理员账号。新增管理员入口仍然需要数据库保存账号与权限，不能用来省掉 PG；当前功能不需要额外管理员登录页面。

## 本地启动（先不连接 MongoDB）

准备 Python >=3.11、Poetry、Node.js 22 / npm 和 Docker Desktop。完整配置、PostgreSQL 初始化、Ollama 和前端构建部署步骤见 [本地部署指南](docs/LOCAL_DEPLOY.md)。

已有 SQL 数据库先按指南备份并执行迁移，新增的 `analyze_flows.debate_rounds` 字段用于保存自定义轮数；新库由初始化流程建立。

从仓库根目录安装后端依赖，已有 `.env` 时保留原文件：

```bash
poetry install
[ -f .env ] || cp .env.example .env
```

按指南设置 `.env` 中的 PostgreSQL 密码、`DATABASE_URL`、`JWT_SECRET` 和 `APP_ENCRYPTION_KEY`，先启动 PostgreSQL 并初始化表，再启动后端。命令中的空 URI 强制禁用 MongoDB，即使 Docker 中已有 MongoDB 也不会连接：

```bash
docker compose -f compose.local.yml up -d --wait postgres
MONGODB_URI='' poetry run python -c 'from dotenv import load_dotenv; load_dotenv(); from docker.db_init import main; main()'
MONGODB_URI='' poetry run python -m uvicorn app.backend.main:app \
  --env-file .env --host 127.0.0.1 --port 8001
```

前端在另一个终端运行：

```bash
cd app/frontend
npm ci
VITE_API_URL=/api npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

打开 [本地应用](http://127.0.0.1:5173)，在页面注册并登录。后端健康检查为 [GET /health](http://127.0.0.1:8001/health)，接口文档为 [Swagger UI](http://127.0.0.1:8001/docs)。两个终端均用 `Ctrl+C` 停止。

无需安装 MongoDB 或配置付费行情 key 即可启动；默认 Yahoo 日线在线获取，Finnhub 当前数据需配置 `FINNHUB_API_KEY`，缺失时标记对应证据不足。完整 AI 报告需要在 Settings 保存用户自己的模型 key，或显式选择可用的 Ollama。主机 `.env` 中的付费模型 key 不会自动用于用户分析。账户、设置和报告兼容副本保存在本地 Docker PostgreSQL（端口 5433，命名卷持久化）。

## 文档

- [接手文档](docs/handoffs/2026-10-28-postgres-local.md)
- [本地部署指南](docs/LOCAL_DEPLOY.md)
- [文档索引](docs/README.md)
- [开发与验证](docs/development.md)
- [当前部署说明](docs/DEPLOY.md)
- [Scanner 行为](v2/scanner/README.md)

研究结果用于分析与研究，不构成收益承诺。
