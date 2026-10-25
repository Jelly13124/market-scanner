# Market Scanner / Quant Lab

股票事件扫描、研究报告、策略实验与模拟交易项目。后端为 Python/FastAPI，前端为 React/Vite。默认分支 `main`。

## 当前实现

- 默认行情链路：优先 MongoDB 有效缓存，缺失或不可用时回退 Yahoo 日线和 Finnhub 当前数据；MongoDB 不是启动或分析的必需依赖。
- Analyze 使用 LangGraph，并行章节显式汇合后生成策略、证据和摘要；辩论按有界的独立发言与裁决节点执行。
- 模型支持用户自带 key / Ollama；包括 owner 和后台任务在内，默认不使用主机付费 key。
- 扫描器输出完整 universe 的 detector outcome。启用 MongoDB 后保存完整扫描历史、冻结数据集、报告、节点缓存和 checkpoint；数据库不可用时继续在线执行并明确显示未保存。
- SQL 保留账户、配置、调度、watchlist 和报告兼容副本。旧 LangGraph 执行入口和旧付费行情适配器已删除，FD 显式兼容入口保留。

本地验证与部署验收是不同阶段。MongoDB 的真实 validator/索引、生产迁移和真实模型报告仍需在对应环境验收；本轮先测试完全不连接 MongoDB 的路径。

详细契约见 [需求基线](docs/requirements/market-data-and-analyze.md)，字段关系见 [MongoDB ERD](docs/design/mongodb-market-data-erd.md)，当前工作记录见 [handoff](docs/handoffs/2026-10-24-market-scanner-handoff.md)。

## 本地开发

Python >=3.11。先创建隔离环境并安装 Poetry，再从仓库根目录运行：

```bash
poetry install
poetry run python -m uvicorn app.backend.main:app --host 127.0.0.1 --port 8001
```

前端在另一个终端运行：

```bash
cd app/frontend
npm install
npm run dev
```

前端的 `VITE_API_URL` 应指向后端地址。机密配置仅在本机或部署平台提供，不提交或打印真实密钥。缺少行情/模型配置时，当前功能不保证可用。

## 文档

- [接手文档](docs/handoffs/2026-10-24-market-scanner-handoff.md)
- [文档索引](docs/README.md)
- [开发与验证](docs/development.md)
- [当前部署说明](docs/DEPLOY.md)
- [Scanner 行为](v2/scanner/README.md)

研究结果用于分析与研究，不构成收益承诺。
