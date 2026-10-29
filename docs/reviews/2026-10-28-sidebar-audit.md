# 左侧板块审查 — 2026-10-28

## 后续实现状态

本审查是修改前快照。按用户后续指令，独立 Sectors / Institutional 已移除，Lab 已替换为 Backtest，Paper 已改为用户独立模拟账户；F1（回测股票池归属）、F5（图表鉴权）、F6（兼容对话接口的 Ollama key 门禁）和 F8（普通用户 Paper）已修复。F2/F3/F4/F7 不在这轮板块调整的完成声明内。

## 结论与边界

当前是多个已有功能的集合，核心模块已有前后端和 SQL 持久化，但尚不能视为所有板块完整、普通用户可顺畅使用的成品。共确认 8 个需修复的问题：3 个 P1、5 个 P2。优先修复越权访问、无鉴权的重型任务和空流程触发全量分析。

本轮以代码审查为主，沿侧栏入口追踪组件、service、FastAPI 路由、权限、仓储和执行器；部分页面用于核对实际状态。功能探针使用隔离内存 SQL、虚构用户，模型、行情加载和全市场构建均被替换为受控测试对象，未对实际用户记录做增删改，未调用付费模型，未连接 MongoDB。没有在本轮修改业务代码。

现有相关回归 108 passed，并不覆盖下述全部边界。完整 AI 报告质量、真实全市场 Scanner/Screener、Lab 长期回测表现及机构数据源可用性不在本轮实测结论内。

## 板块完成度

| 板块 | 代码已具备 | 当前缺口与判断 |
| --- | --- | --- |
| Home | 欢迎页、功能入口、模型/报告/watchlist/调度检查清单 | 基础引导已具备；只在加载时检查部分状态，不能代替功能验收 |
| Watchlist | 用户隔离的列表 CRUD、加删股票、搜索、报价、进入分析 | 核心链路较完整；美股报价需 Finnhub，缺 key 时不能展示完整实时行情；刷新以手动/窗口焦点为主 |
| Screener | 多字段筛选、排序、预设、后台快照更新、加入 watchlist/分析 | 功能较多但本地没有初始快照；主要为美股，CN 在选择器中禁用；更新接口缺鉴权，见 F2 |
| Sectors | 美股板块汇总和进入带板块筛选的 Screener | 基础展示层，依赖 Screener 已有快照；Refresh 只重新读取汇总，不构建数据；读取失败也会显示空状态 |
| Scanner | 配置、股票池、detector、运行、进度、Top N、定时与分析联动 | 核心链路较完整；需创建配置、小范围真实行情验收；MongoDB 关闭时 SQL Top N 不等于完整历史 |
| Analyze | 预置章节画布、人物视角、轮数、保存模板、分析、报告 | 可配置模板，执行依赖仍固定，连线不决定执行顺序；空章节、人物清空、调度配置存在问题，见 F3/F4/F7 |
| Institutional | Gamma/GEX 估算与 FINRA short-volume 代理指标 | 辅助查询模块；数据源可能部分缺失，不能当成真实机构持仓/资金流，尚未做本次实源验收 |
| Reports | 按用户列表、HTML 阅读、批量删除、报告变化刷新 | 基础链路较完整，HTML 已通过带鉴权 fetch 获取 blob；还需真实完整报告验收 |
| Paper | 全局模拟组合表现、指标、曲线、评估结果 | 当前是管理员工具，不是普通用户自己的模拟账户；侧栏无权限隐藏，普通用户必定 403，见 F8 |
| Lab | 策略 CRUD、对话、JSON spec、回测、历史、指标与图表 | 闭环存在，但有嵌套资源越权、图片鉴权和 Ollama 门禁错误，见 F1/F5/F6；暂不宜作为完整主线演示 |

“较完整”表示组件、路由与持久化存在且相关接口回归通过，不表示已完成真实行情、真实模型与所有边界的端到端验收。

## 已确认问题

### F1 · P1 · Lab 可通过策略引用其他用户的私有 watchlist

位置：[universe.py](../../src/lab/engine/universe.py) 第 28 行；调用链：[backtest_runner.py](../../src/lab/backtest_runner.py) 第 81 行、[lab.py](../../app/backend/routes/lab.py) 第 334 行。

回测只检查策略属于当前用户，随后用 `get_by_id_unscoped(spec.watchlist_id)` 读取股票池。构造自己的策略并填写别人的 watchlist ID，即可使用对方的私有列表；回测结果及交易明细还可能暴露列表股票。

复现：用户 1 直接 GET 用户 2 的 watchlist 返回 404；同一用户创建引用该 ID 的策略并提交回测返回 200，受控行情加载器收到用户 2 的 `SPY`、`MSFT`。没有读取真实用户的数据或发起真实行情请求。

修复方向：把 owner 贯穿回测执行器与股票池加载器，使用 owner-scoped 查询；创建、编辑、AI patch 和运行阶段都应验证 watchlist 归属。

### F2 · P1 · 未登录请求可以启动全市场快照更新

位置：[screener.py](../../app/backend/routes/screener.py) 第 151–164 行。

`POST /screener/snapshot/refresh` 没有用户依赖、权限判断或重型接口限流装饰器，直接调用 `start_refresh`。公开行情读取可以匿名，但启动抓取并写入共享数据属于另一种权限：外部访问者可反复占用行情配额和后台资源。

复现：不给 Authorization，替换实际后台构建器后 POST 返回 200，构建器被调用。未实际触发全市场抓取。进程内锁只能限制同时运行一个任务，不能代替鉴权或防止连续触发。

修复方向：增加登录/明确的刷新权限及限流，保留已有并发锁；公开 GET 行情不必因此改成私有数据。

### F3 · P1 · Analyze 选择零章节会被转为完整 20 章节

位置：[research.py](../../app/backend/routes/research.py) 第 271–274 行；[analyze-toolbar.tsx](../../app/frontend/src/components/panels/analyze/analyze-toolbar.tsx) 第 228–233 行。

后端把 `[]` 和 `None` 都按 false 处理并补成 `SECTION_ORDER`；前端 Run 只检查输入节点和模型，不检查章节数。因此界面可以显示 Run (0)，实际却执行全量报告，带来与选择相反的行为及意外模型调用。

复现：`AnalyzeRunRequest(included_sections=[])` 转成内部请求后章节数为 20，未调用任何模型。

修复方向：区别 `None`（默认全部）与 `[]`（拒绝或明确不运行），前后端都校验至少一个有效章节。

### F4 · P2 · 保存流程时无法清空最后一个人物覆盖

位置：[flow-list.tsx](../../app/frontend/src/components/panels/analyze/flow-list.tsx) 第 97–103 行；[analyze_flows.py](../../app/backend/routes/analyze_flows.py) 第 95–103 行；[analyze_flow_repository.py](../../app/backend/repositories/analyze_flow_repository.py) 第 110–113 行。

前端没有人物覆盖时发 `persona_overrides: null`，仓储却把 null 当作“不更新”。仓储支持 `clear_overrides`，但路由没有根据请求字段是否明确提供来传入。

复现：保存 valuation=Buffett，再 PATCH null，响应 200 但仍保留 Buffett。重新加载后用户以为移除的人物会回来。

修复方向：路由根据 `model_fields_set` 区分省略与明确 null，正确清空；添加“人物 → objective → 保存 → 重新加载”回归。

### F5 · P2 · Lab 回测三张图表无法携带 Bearer 登录令牌

位置：[backtest-result.tsx](../../app/frontend/src/components/panels/lab/backtest-result.tsx) 第 51–55 行及后续图表；[lab.py](../../app/backend/routes/lab.py) 第 404–409 行。

图表使用原生 `<img src>`，但对应端点只接受 Authorization Bearer；全局 fetch 拦截器不会拦截浏览器原生图片加载，refresh cookie 也不能满足这个接口。

复现：同一有效回测图表，不带 Authorization 返回 401，带有效 Bearer 返回 200。即使回测完成，页面仍可能只显示指标而看不到曲线。

修复方向：带鉴权 fetch 图片后用 blob URL 展示并回收 URL，保持后端 owner 校验；不要为修图表移除鉴权。

### F6 · P2 · Lab 对话在 Ollama 模式错误要求 None API key

位置：[lab.py](../../app/backend/routes/lab.py) 第 209–213 行；[research.py](../../app/backend/routes/research.py) 第 255–258 行。

研究模块对 Ollama 返回的必需 key 名为 None，但 Lab 无条件执行 `require_api_key(provider_key)`，在实际模型调用前即失败。

复现：隔离环境选择 Ollama，正常用户发送策略消息返回 400：`Add your None API key in Settings to run this.`，模型调用数为 0。

修复方向：Ollama 走模型服务就绪检查；仅实际需要 key 的供应商走用户 key 校验，继续禁止隐式付费回退。

### F7 · P2 · Analyze 定时任务没有继承用户当前分析流程与市场

位置：[schedule-ticker-dialog.tsx](../../app/frontend/src/components/panels/analyze/schedule-ticker-dialog.tsx) 第 54–58 行；[report_schedules.py](../../app/backend/routes/report_schedules.py) 第 52–64 行；[scheduler_service.py](../../app/backend/services/scheduler_service.py) 第 522–531 行。

保存时只有 ticker、cron 和语言；章节、人物覆盖、辩论参数、目标、风险和 market 都没有保存。后台重新构造默认请求，强制 `use_personas=False`，默认全章节、US 市场。

代码及 schema 复核：传入 market/章节/轮数等额外字段也不会保留，Pydantic 输出仅有 tickers、cron_expr、report_language、is_enabled。A 股输入还会丢失 CN 路由，不能将当前 Schedule 按钮理解为“定时运行我的画布流程”。

修复方向：保存 owner-scoped 流程快照/明确引用，贯穿 market 和分析参数；或把现有入口明确标为默认完整报告调度，避免误导。

### F8 · P2 · 普通用户可见 Paper 入口却必定无权使用

位置：[left-sidebar.tsx](../../app/frontend/src/components/panels/left/left-sidebar.tsx) 第 67 行；[paper.py](../../app/backend/routes/paper.py) 第 43–50 行。

侧栏对所有用户展示 Paper，但指标 API 明确限制 superuser，因为模拟组合是全局 host book。普通用户点击后直接出现 host-only 403，同时仍显示无数据表格。

复现：当前普通账号页面和隔离普通账号请求均得到 403。这是权限与产品入口不一致，而不是 PostgreSQL 无数据造成的。

修复方向：若定位管理员工具，隐藏普通用户入口并提供明确权限说明；若定位用户模拟交易，需要真正的 owner 隔离模型和运行器，不能直接解除 API 权限。

## 建议处理顺序

1. 修 F1/F2/F3，先确保权限和用户分析选择不会失效。
2. 修 F4/F5/F6/F7，补齐模板、回测和调度的实际闭环。
3. 将 Paper 明确为管理员工具，并补齐各页的初始化指引、来源/更新时间与错误说明。
4. 以 Watchlist → 小范围 Scanner/Screener → 自定义 Analyze → Reports 做课程主线，完成一次明确配置模型的小范围真实验收后，再扩展到 Lab/Paper。目前仍不应把画布当成自由 DAG 编辑器。
