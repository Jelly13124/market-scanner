# Market Scanner 项目约束

## 当前文档

- docs/requirements/market-data-and-analyze.md：已确认需求、范围和验收。
- docs/design/mongodb-market-data-erd.md：数据库设计，尚未实现。
- docs/development.md：开发、测试与工程约束。
- docs/DEPLOY.md：当前部署实现和边界。

旧计划和实测笔记已删除，不再要求维护 progress.md/task_plan.md/findings.md。以当前用户指令优先；不要把设计目标写成已经上线。

## 必须保留

- z-score 使用有意义的 std floor；signal/detector 缺数据按契约降级；None 与未触发事件不同。
- HTTP client/session 每个 worker 独立。保留旧保存配置 alias/retired 名，除非实施并验证数据迁移。
- 用户模型 key 显式注入，禁止隐式消耗主机付费 key；不打印/提交真实环境配置或把 key 存入报告/checkpoint。
- Analyze 使用 LangGraph；历史行情优先可选 MongoDB 缓存，缺失时回退 Yahoo/Finnhub；不把数据库缺失当成分析失败。保留有效旧 agent，避免双主线。
- src/research/prompts/*.md 为运行时输入，不属于可删除的历史笔记。

## 开发

使用 Python >=3.11 的项目环境，不硬编码旧电脑路径。启动与测试见 docs/development.md。只终止本项目进程，不按语言名批量结束进程。

文档清理只改文档、注释和 docstring；实现行为变化应单独说明并验证。
