# 开发与验证

Python 要求 >=3.11，使用项目隔离环境；不要沿用旧电脑的绝对解释器路径。Python 依赖见 pyproject.toml/poetry.lock，前端依赖见 app/frontend/package.json。

## 启动和检查

后端：`poetry run python -m uvicorn app.backend.main:app --host 127.0.0.1 --port 8001`。
前端：在 app/frontend 下运行 `npm install`、`npm run dev`。URL 以启动日志为准。
健康检查：GET /health。只结束本项目的进程，不批量结束其他 Python/Node 进程。

```bash
poetry run pytest v2/scanner v2/self_evolve src/paper_trading -q
poetry run pytest tests/test_detector_invariants.py -q
```

前端在其目录运行 `npm run build`、`npm run lint`。数据适配器、报告/鉴权及图改造需另运行相应测试；上述命令不是完整验收。

现有 CI 只覆盖部分离线测试；Docker 构建也不等于完整 TypeScript 和运行时验证。带真实行情/模型请求的测试必须明确控制外部请求与费用，不能读到 key 就自动运行。

## Scanner 必须保留的约束

1. 所有 z-score 分母必须有有意义的 std floor，不能只用 `sigma or epsilon` 处理恰好零的情况。
2. detector/signals 遇到缺数据按契约返回，不向调用方抛未处理异常。
3. `None` 表示该 detector 无足够数据，`EventTrigger(triggered=False)` 表示已运行但未触发，二者不能混淆。
4. HTTP client/session 每个 worker 独立，不能用共享 requests.Session 冒充线程安全。
5. 保留已保存配置的 alias/retired detector 名兼容，除非实施并验证数据库迁移。
6. 未验证 point-in-time 的财务快照不用于声称无前视的历史评估；信号效果不得从旧实测结论直接推广。

规则实现参考 tests/_detector_lint.py、tests/test_detector_invariants.py 和当前 detector 源码。价格/报告的未来契约见 [需求基线](requirements/market-data-and-analyze.md)。

## 机密和权限

不打印或提交真实环境配置、用户 key、数据库 URI。用户请求必须显式传 owner 及其允许使用的模型配置；密钥不得进入图 checkpoint 或报告。旧 LangGraph Pipeline 执行已退役；其历史记录保留读取。其余模型调用仍须按需求验证密钥隔离。

## 可选 MongoDB 与本地无数据库验收

不配置 `MONGODB_URI`（或显式设为空字符串）即可使用在线行情和 SQL 报告副本。Yahoo 日线不需要付费行情 key；Finnhub 功能按配置的免费 key 与实际权限降级。分析仍需显式 BYOK 或可连接的 Ollama；MongoDB 缺失不会引发模型供应商切换。

`MARKET_CACHE_TTL_SECONDS` 控制公共数据响应的新鲜度，历史证据不设 TTL 删除。实时 quote 绕过 MongoDB。`LLM_CACHE_TTL_SECONDS` 的过期检查在读取时执行。`force_rerun` 绕过报告和节点复用；`resume_run_id` 仅在能验证 owner、版本和原 dataset 的 MongoDB checkpoint 上恢复。

准备 MongoDB 时，先在测试数据库运行以下命令；不在无 MongoDB 验收期间执行：

```bash
poetry run python -m scripts.mongo_history install-schema --apply
poetry run python -m scripts.mongo_history migrate
poetry run python -m scripts.mongo_history migrate --apply
poetry run python -m scripts.mongo_history verify
```

迁移先预览，应用后校验数量并抽样核对 owner、正文、HTML 和策略/回测；SQL 继续保留作为回滚读路径。不得将 `legacy_topn_only` 当成全量扫描历史。

无 MongoDB 回归可显式运行 `MONGODB_URI='' poetry run pytest tests/test_mongo_fallback.py tests/research tests/test_scanner_service.py -q`。该存储测试仅使用进程内模拟 MongoDB，不连接 Docker。

完整无 MongoDB API smoke：`MONGODB_URI='' poetry run python -m scripts.smoke_no_mongo`。该命令显式读取少量真实 Yahoo 数据，使用临时 SQL、禁用调度，只运行数据健康/缺失数据章节，断言模型调用为 0；不测试真实 AI 质量，不连接 Docker MongoDB。
