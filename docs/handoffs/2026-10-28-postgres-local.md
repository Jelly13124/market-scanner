# 本地 PostgreSQL 接续 — 2026-10-28

本页补充并优先于 [10 月 25 日交接](2026-10-25-local-validation.md) 中的默认 SQL 存储与人物辩论描述。MongoDB 和真实模型的未完成验收仍沿用该交接。

## 后续板块调整（同日）

- 用户要求删除左侧 Sectors、Institutional，增加独立 Backtest，将 Paper 开放给普通用户。两个独立页面及 Institutional 独立 API 已移除，Analyze 内共享的分析代码保留；旧保存的两个页签在重新加载时过滤，原 Lab 页签迁移为 Backtest。
- Backtest 支持策略列表、股票池、日期、均线/RSI 入场规则、止损、初始资金、手续费/滑点、历史结果及鉴权图片。高级 JSON 编辑保留；不依赖 AI key。后端继续使用已有 `/lab/*` API 以兼容已保存策略。
- 回测股票池从创建/编辑/应用 patch 到运行阶段均检查 watchlist owner，执行器也必须显式传入 owner。修复样本外模拟初始资金与指标基准不一致的问题，使用 IS 期末权益作为 OOS 的共同初始值，原始策略配置不被修改。
- 个人 Paper 使用新表 `user_paper_accounts`、`user_paper_positions`、`user_paper_trades`，迁移 `c6d9e2f4a810` 已在备份后的本地 PostgreSQL 上应用。每用户一个独立 USD 账户，支持模拟买卖、持仓、手动估值、已实现/未实现盈亏及最近 200 条成交；Decimal 计算，账户行锁防止并发透支。
- Paper 的成交价/估值为用户手动输入，明确标注非实时报价、非券商真实执行，暂不支持费用、杠杆或卖空。旧全局 host book 保留但不暴露给普通用户；旧 cron 默认关闭，可通过 `ENABLE_HOST_PAPER_JOBS=true` 单独启用。
- 开发前端改用 `VITE_API_URL=/api` 和 Vite 同源代理到后端 8001，refresh cookie 路径同步重写；构建后由后端托管时仍使用对应后端 URL 构建。
- 验证：221 项相关回归通过，TypeScript/Vite 构建通过；PG 两个同时买单仅一个成交，租户隔离和盈亏通过；SPY/AAPL 的 2024 年真实 Yahoo 回测返回 IS 176 / OOS 76 个估值点，鉴权图表 200，跨用户 watchlist 404。模型调用为 0，MongoDB 禁用。
- 浏览器以临时普通账户验证了新导航、Paper 创建/模拟成交/手动估值和 Backtest 策略创建/参数界面；临时用户及关联记录已清理，现有用户数据未改动。截图在被忽略的 `outputs/reviews/` 中。
- 本轮未顺带修复审查报告中的 F2/F3/F4/F7；进展已在 [审查文档](../reviews/2026-10-28-sidebar-audit.md) 标注，不能宣称所有审查项已清零。

## 用户确认与当前实现

- 课程要求使用 PostgreSQL，保留用户管理。Web SQL 默认 PostgreSQL，保存账户、密码哈希、加密用户 key、流程模板、配置、调度及 SQL 报告；连接失败不回退 SQLite。SQLite 仅用于显式隔离测试和保留的旧库备份。
- `compose.local.yml` 启动独立 PostgreSQL 16，绑定 `127.0.0.1:5433`，数据在命名卷。`.env` 的 PostgreSQL 凭据只保存在本机且被 Git 忽略；不得读取并输出其值。
- 本地旧 SQLite 经检查没有用户或业务记录，已备份并保留，没有需要搬迁的旧记录。当前运行的后端已连接 PostgreSQL，MongoDB 仍显式禁用，用户原有 MongoDB 容器未操作。
- 修复 `screener_presets.schedule_enabled` 使用整数默认值导致 PostgreSQL 建表失败的问题，改用 SQLAlchemy 的布尔默认值。
- 投资人物精简为 Buffett、Lynch、Wood、Burry、Druckenmiller。自定义辩论 1–5 轮保留，默认 1 轮，每次两人发言后一次裁决；调用数为 `2 × 轮数 + 1`，不包含路由和其他章节。
- 补齐流程模板保存/加载辩论开关与轮数，新增 `analyze_flows.debate_rounds` 及迁移 `a4c8d2e6f901`。旧模板中的已删除人物在加载时回到客观模式。

## 已完成本地实库验证

- PostgreSQL 全部 ORM 表初始化与 Alembic stamp 成功，27 张表（包含版本表），版本为 `a4c8d2e6f901`。
- 实际运行中的 API 完成注册、登录、密码哈希入库、流程模板创建/修改/读取/删除，并直接查询 PostgreSQL 确认数据。临时测试账号及模板均已清理。
- 鉴权、租户隔离、流程仓储/API、轮数迁移回归：126 passed。回归显式使用临时 SQLite，与上述 PostgreSQL 实库验收分别记录。
- 本地测试曾将连接密码带入失败输出，已立即轮换数据库密码、更新本机配置、重建容器环境并重启后端。旧密码已失效。
- 前端 `http://127.0.0.1:5173` 与后端 `/health` 均返回 200；轮换后 PostgreSQL 连接复核通过。无 MongoDB 客户端创建，无付费模型调用。

## 运行与后续

安装、启动、停止和备份见 [本地部署指南](../LOCAL_DEPLOY.md)。Fly 配置已移除硬编码 SQLite URL，但未发布到远端；下次远端部署前需配置 PostgreSQL secret，并独立规划旧线上数据迁移。

当前画布支持组合预置章节、人物视角、辩论参数并保存模板；执行顺序和依赖仍由后端 LangGraph 决定，画布连线不改变执行顺序。自定义 agent/提示词/数据工具和自由 DAG 尚未实现。

## 2026-10-29：功能标注与安装说明

- Backtest 页面标注“基础版”，Paper 标注“手动模拟版”，中英文说明明确尚未实现的功能。
- README 补充能力/限制表、LangChain 调用与 LangGraph 编排关系，以及 PostgreSQL 与可选 MongoDB 的职责。
- 本地部署指南补充工具安装、获取源码、首次配置、普通用户注册、日常重启、已有安装升级、备份恢复和验收步骤。
- 管理员入口不替代数据库；本轮未新增管理员角色或免数据库登录，使用 Docker PostgreSQL 避免手动安装数据库服务。
- 本轮只调整展示与文档，没有新增运行时兜底或业务抽象。

### Paper 暂停开放

用户确认目前手动估值不适合开放使用。侧栏 Paper 改为不可点击的“开发中”，旧保存标签不再恢复；保留占位页避免已有页面继续渲染操作表单。主 API 不挂载个人 Paper router，原型代码、数据库表及已有记录保留。README 和安装验收步骤同步更新。没有引入功能开关或新的降级分支。

## 2026-10-29：main 审查问题修复

免登录实验暂停，未合入 main，未完成改动保存在 stash。当前仍使用 PostgreSQL 和普通用户登录。

按优先顺序先修复空章节、快照刷新鉴权/限流、人物清空持久化、调度配置快照；再修复回测次日开盘执行、交易统计双边费用和 OOS 基准区间。新增 `report_schedules.analysis_config`，迁移版本 `d7e3f901b625`。旧调度默认行为保留，旧回测必须重新运行才能采用新逻辑。

模型调用仍为 LangChain，编排仍为 LangGraph。相关回归 211 passed；后续调度兼容/迁移测试 4 passed（含前述重复 2 项）。前端构建通过。真实 PG 迁移和临时账号 API smoke 通过，临时数据已清理，没有付费模型调用。详细证据见 `docs/reviews/2026-10-29-main-review.md`。
