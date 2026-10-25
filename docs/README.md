# 文档索引

## 当前需求与设计

- [完整物理 ERD](design/mongodb-full-erd.md)：全部集合和字段、PK/FK、复合与条件 UK、关系基数及业务完整性。
- [Mermaid ERD 源文件](design/mongodb-full-erd.mmd)：可导入 Mermaid 编辑器。

- [新需求基线](requirements/market-data-and-analyze.md)：已确认范围、当前差距、接口边界与验收。
- [MongoDB ERD v2](design/mongodb-market-data-erd.md)：业务与运维分层、历史新闻/财报、时间语义与数据生命周期。
- [MongoDB 字段字典](design/mongodb-data-dictionary.md)：字段类型、必填、PK/UK/FK 与查询索引。
- [MongoDB 物理定义](design/mongodb-schema.json)：validator 与命名索引设计，尚未执行。

## 接手

- [2026-10-24 Handoff](handoffs/2026-10-24-market-scanner-handoff.md)：当前工作区、已完成设计、每日扫描入库要求、待实现与接手顺序。

## 当前运行与开发

- [开发与验证](development.md)
- [部署说明](DEPLOY.md)
- [应用开发](../app/README.md)
- [后端](../app/backend/README.md)
- [前端](../app/frontend/README.md)
- [数据与量化模块](../v2/README.md)
- [Scanner](../v2/scanner/README.md)
- [运行时研究提示词](../src/research/prompts/README.md)

旧计划、历史设计和实测笔记已按用户要求删除。实验脚本仍可产生新的评估产物；产物不是当前需求来源。以 requirements 中的确认需求、design 中的接口设计及当前代码分别判断目标、设计与已实现行为，三者不可混写。

最新本地验收与接续工作见 [2026-10-25 交接](handoffs/2026-10-25-local-validation.md)。
