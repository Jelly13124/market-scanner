# 本地部署指南

本指南先运行不连接 MongoDB 的版本：行情在线获取，账户、设置、流程模板和报告兼容副本保存在本地 PostgreSQL。Docker 中的 MongoDB 可以保持原样，本节命令不会连接或写入它。MongoDB 缓存缺失不会阻止在线分析，但网络、行情权限和模型可用性仍决定报告能获得哪些证据。

## 安装前先了解

本地需要三个服务：浏览器前端（5173）、Python 后端（8001）、Docker PostgreSQL（5433）。MongoDB 和 Ollama 均为可选组件。Docker Desktop 只负责运行数据库，前后端在宿主机启动。

| 使用目标 | 必需配置 |
| --- | --- |
| 注册登录、配置流程 | PostgreSQL、JWT 密钥、用户 key 加密密钥 |
| 历史 Backtest | 以上配置和可访问 Yahoo 的网络，无需模型 key |
| AI Analyze | 以上配置和用户模型 key，或已启动的 Ollama |
| 更完整的当前行情证据 | 可选 Finnhub key，具体受接口权限限制 |

管理员登录不能替代数据库。当前没有预设管理员账户，安装后直接注册普通账号即可。课程要求使用 PostgreSQL，因此这里通过 Docker 启动 PG，免去手动安装数据库服务；仍需保留容器和数据卷。

首次安装按第 1–5 节操作。已有项目使用文末“更新已有安装”；日常使用见“日常重启”。

## 1. 获取项目、安装依赖

准备 Git、Python >=3.11（建议本地使用 3.12）、Poetry、Node.js 22 或更高版本 / npm，以及 Docker Desktop。先启动 Docker Desktop，等待 Docker 引擎就绪。

macOS 已安装 Homebrew 时，可用以下命令安装开发依赖；Docker Desktop 也可使用已有安装：

```bash
brew install git python@3.12 node@22 pipx
pipx ensurepath
pipx install poetry
brew install --cask docker
```

安装后重新打开终端。若 `node` 不在 PATH，按 `brew info node@22` 显示的说明配置 PATH。Windows 可在 WSL2 中运行项目并启用 Docker Desktop 的 WSL 集成；下文使用 Bash/Zsh 命令，不能直接复制到 PowerShell。

首次获取项目：

```bash
git clone https://github.com/Jelly13124/market-scanner.git
cd market-scanner
```

已有源码则进入现有项目目录，不必重新 clone。检查工具和 Docker：

```bash
python3.12 --version
poetry --version
node --version
npm --version
docker compose version
docker info --format '{{.ServerVersion}}'
```

选择 Python 环境并安装后端依赖：

```bash
poetry env use python3.12
poetry install
poetry run python --version
[ -f .env ] || cp .env.example .env
```

如果安装的是其他满足要求的 Python，将 `python3.12` 换成对应命令。所有后端命令从仓库根目录执行，前端命令按说明进入 `app/frontend`。首次 `poetry install`、`npm ci` 和拉取数据库镜像都需要网络。

## 2. 配置本地环境

编辑根目录 `.env`，确认以下配置。已有配置时只修改需要的字段，不覆盖原密钥：

```dotenv
ENVIRONMENT=development
REQUIRE_EMAIL_VERIFICATION=false
SCANNER_DATA_PROVIDER=hybrid
POSTGRES_DB=market_scanner
POSTGRES_USER=market_scanner
POSTGRES_PASSWORD=替换为本地随机密码
DATABASE_URL=postgresql+psycopg2://market_scanner:替换为同一个密码@127.0.0.1:5433/market_scanner
MONGODB_URI=
MONGODB_DATABASE=market_scanner
MONGODB_TIMEOUT_MS=500
FINNHUB_API_KEY=
RESEARCH_MODEL_PROVIDER=DeepSeek
RESEARCH_MODEL_NAME=deepseek-chat
ENABLE_HOST_PAPER_JOBS=false
JWT_SECRET=替换为下面生成的随机值
APP_ENCRYPTION_KEY=替换为下面生成的Fernet密钥
```

分别生成 PostgreSQL 密码、JWT 密钥和用户 API key 的加密密钥，将输出粘贴到对应字段。PostgreSQL 密码在 `POSTGRES_PASSWORD` 与 `DATABASE_URL` 中保持一致：

```bash
poetry run python -c "import secrets; print(secrets.token_hex(24))"
poetry run python -c "import secrets; print(secrets.token_urlsafe(48))"
poetry run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

`APP_ENCRYPTION_KEY` 保存后保持稳定，丢失或更换会导致已有加密 key 无法解密；更换 `JWT_SECRET` 会使原登录令牌失效。`.env` 已被 Git 忽略，不提交真实配置。

`DATABASE_URL` 指向 PostgreSQL。默认端口为本机 `5433`，映射到容器的 `5432`。应用不会因 PostgreSQL 不可用而自动退回 SQLite；SQLite 只保留为旧数据备份和显式指定的隔离测试后端。不需要 Financial Datasets key；Yahoo 日线无需 key。可选的 `FINNHUB_API_KEY` 用于当前行情等证据，未配置或权限不足时相应数据会缺失，不会凭空补齐。

本地关闭邮箱验证后可直接注册登录，无需先配置 Resend；未配置邮件时，注册可能出现邮件发送失败日志，检查注册与登录是否成功即可。

## 3. 启动 PostgreSQL、初始化表并启动后端

从仓库根目录启动项目专用 PostgreSQL。Compose 只管理这里定义的 PostgreSQL，不会操作已有 MongoDB：

```bash
docker compose -f compose.local.yml up -d --wait postgres
MONGODB_URI='' poetry run python -c 'from dotenv import load_dotenv; load_dotenv(); from docker.db_init import main; main()'
```

首次初始化建立 ORM 表并记录 Alembic 版本；已有带迁移版本的 PostgreSQL 则执行增量升级。用户、密码哈希、加密后的用户 API key、流程模板、配置和 SQL 报告全部写入 PostgreSQL。

数据库数据保存在 Compose 的 `postgres_data` 命名卷中，停止容器后仍保留。`POSTGRES_PASSWORD` 仅在空数据卷首次初始化时创建数据库密码；已有卷更改 `.env` 不会自动修改数据库内的密码。

已有 SQLite 不会自动导入 PostgreSQL，也不会删除。若旧库已有用户或业务记录，应先备份、规划 SQL 数据迁移，再切换；不要把修改连接地址当作已迁移旧记录。旧 PostgreSQL 升级前也需备份。

启动后端：

```bash
MONGODB_URI='' poetry run python -m uvicorn app.backend.main:app \
  --env-file .env --host 127.0.0.1 --port 8001
```

`--env-file` 在导入应用前加载配置，确保数据库和鉴权模块读取正确值。命令行的空 `MONGODB_URI` 优先于 `.env`，用于本轮完全绕过 MongoDB 的验收。先用单个后端进程运行，当前进程内调度尚未支持多个 worker 协调。

在另一个终端检查：

```bash
curl --fail http://127.0.0.1:8001/health
```

预期返回 `{"status":"ok"}`。接口文档在 <http://127.0.0.1:8001/docs>；健康检查成功仅表示服务可用，不代表行情或模型已完成验收。

## 4. 启动前端并登录

在新的终端从仓库根目录执行：

```bash
cd app/frontend
npm ci
VITE_API_URL=/api npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

打开 [本地应用](http://127.0.0.1:5173)，使用自己的邮箱和密码注册，再登录。`REQUIRE_EMAIL_VERIFICATION=false` 时本地无需邮件验证，不存在通用管理员密码。前后端统一使用 `127.0.0.1`，避免混用 `localhost` 引起 cookie 和登录状态问题。开发模式使用 `VITE_API_URL=/api`，由 Vite 将同源 `/api` 请求代理到后端 8001，并调整 refresh cookie 路径，避免跨端口预检影响登录和请求。不要省略该值，因为各旧 service 的默认地址并不统一。

开发模式允许的前端来源默认包含 `http://127.0.0.1:5173` 和 `http://localhost:5173`。若改端口，需同步修改后端 `.env` 的 `FRONTEND_ORIGINS` 并重启后端。

## 5. 配置分析模型

Analyze 画布的 Debate 节点可以启用/关闭人物辩论，并自定义 1–5 轮，默认 1 轮。保存及重新加载流程模板会保留轮数和开关。每次选两位人物，辩论部分调用数为 `2 × 轮数 + 1`，不包含人物路由和其他报告章节的调用。旧模板引用已删除的人物时，加载后相应章节回到客观模式。

保存轮数使用 SQL 字段 `analyze_flows.debate_rounds`，由第 3 节的初始化/迁移命令建立；不会自动连接或迁移 MongoDB。

完整 Analyze 报告选择以下一种方式：

| 方式 | 配置 | 验证 |
| --- | --- | --- |
| 用户模型 key | 默认 `DeepSeek` / `deepseek-chat`；登录后在 Settings 保存对应供应商的用户 key。更换供应商时同时设置 `RESEARCH_MODEL_PROVIDER` 和 `RESEARCH_MODEL_NAME`，然后重启后端 | 确认模型状态就绪，再运行一次单股票 Analyze；实际调用按供应商计费 |
| 本地 Ollama | 安装并启动 Ollama，拉取模型；在 `.env` 中设置 `RESEARCH_MODEL_PROVIDER=Ollama`、`RESEARCH_MODEL_NAME=已安装的完整模型标签`、`OLLAMA_BASE_URL=http://127.0.0.1:11434`，然后重启后端 | 用 `ollama list` 确认标签，页面确认模型就绪；模型需支持分析所需的结构化输出 |

本地模型标签应使用 `ollama list` 显示的实际值，不要直接填中文占位符。未使用 Ollama 时，启动日志提示未安装 Ollama 不代表后端启动失败。

用户分析不会自动使用主机环境中的付费模型 key；Ollama 不可用时也不会自动切换付费供应商。MongoDB 和模型是独立配置：关闭 MongoDB 仍可运行 AI 分析，前提是已配置可用模型。

## 6. 先验收无 MongoDB 路径

从仓库根目录执行现有 API smoke：

```bash
MONGODB_URI='' poetry run python -m scripts.smoke_no_mongo
```

该脚本使用临时 SQLite、禁用调度、请求少量真实 Yahoo 数据，只运行数据健康与缺失数据章节，并断言模型调用为零。不会连接 Docker MongoDB，也不会写入日常使用的 PostgreSQL。它验证在线数据回退和报告保存链路；真实 AI 报告质量需要完成上一步后再单独验收。

可进一步在页面创建小范围 Scanner 配置，再运行单股票 Analyze，核对数据缺失说明和报告历史。MongoDB 未配置时，完整扫描历史、冻结数据集、节点缓存及 checkpoint 不会持久化到 MongoDB；SQL 仍保留其支持的报告兼容副本。需要原 dataset/checkpoint 的断点恢复不能仅靠 SQL 完成。

## 7. 将构建后的前端交给后端托管

如果日常使用不需要 Vite 开发服务，可构建一次前端，由 FastAPI 提供静态页面：

```bash
cd app/frontend
VITE_API_URL=http://127.0.0.1:8001 npm run build
```

构建后停止原后端，从仓库根目录重新运行第 3 节的后端命令，使其挂载 `app/frontend/dist`。关闭 Vite 终端，浏览器改为打开 <http://127.0.0.1:8001>。本地需保持后端进程及 PostgreSQL 容器运行。

`VITE_API_URL` 在构建时写入前端资源；改变后端地址后需重新构建，不能只修改后端环境变量。以上命令仅绑定本机地址，公网部署见 [部署说明](DEPLOY.md)。

## 日常重启

保留之前的 `.env`，从仓库根目录启动数据库和后端：

```bash
docker compose -f compose.local.yml up -d --wait postgres
MONGODB_URI='' poetry run python -m uvicorn app.backend.main:app \
  --env-file .env --host 127.0.0.1 --port 8001
```

开发模式另开终端，按第 4 节启动 Vite；没有更新依赖时无需重复 `npm ci`。若采用第 7 节构建方式，直接打开后端 8001，无需 Vite。

## 更新已有安装

先保存自己的源码改动，再拉取代码；工作区有未提交修改时不要直接覆盖。停止本项目的前后端进程，保留 PostgreSQL 运行，并按下一节备份数据库。然后在仓库根目录执行：

```bash
poetry install
MONGODB_URI='' poetry run python -c 'from dotenv import load_dotenv; load_dotenv(); from docker.db_init import main; main()'
```

本次更新包含辩论轮数字段与个人 Paper 账户三张表。初始化命令会升级已有带 Alembic 版本的 PostgreSQL；没有迁移记录的旧业务库需要单独核对 schema，不能直接当作空库初始化。

前端有依赖变更时执行 `npm ci`，随后按开发或构建方式重新启动。保留原 `APP_ENCRYPTION_KEY` 和数据库凭据，不要重新复制 `.env.example` 覆盖现有配置。

## 停止、备份与后续启用 MongoDB

在各服务终端按 `Ctrl+C` 停止。保留 `.env`、PostgreSQL 命名卷和加密密钥以便重启恢复账户与配置。只结束本项目的进程。

停止 PostgreSQL：`docker compose -f compose.local.yml stop postgres`。再次启动使用第 3 节命令。日常停止不删除命名卷。

备份当前 PostgreSQL：

```bash
mkdir -p outputs/local-backups
docker compose -f compose.local.yml exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "outputs/local-backups/postgres-$(date +%Y%m%d-%H%M%S).dump"
```

备份恢复到一个已创建的**空 PostgreSQL 数据库**时，将文件路径换成实际备份：

```bash
docker compose -f compose.local.yml exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-privileges' < outputs/local-backups/你的备份.dump
```

恢复已有非空库需要先安排数据替换，不直接运行上述命令。日常停止使用 `stop`，不要用 `down -v` 删除数据卷。数据库备份之外也要单独保管原 `.env` 中的加密密钥。

旧 SQLite 文件 `app/backend/hedge_fund.db` 和备份可继续保留，当前应用不再写入它。

后续需要接入 Docker MongoDB 时，在 `.env` 设置实际连接 URI，启动命令去掉 `MONGODB_URI=''` 前缀。此后优先读取有效 MongoDB 缓存；空库或不可用时继续在线获取，当前 quote 仍直接走在线接口。缓存填充不等同于已经建立完整历史或完成迁移。

本轮不执行 MongoDB schema 安装和迁移；准备好测试数据库后按 [开发与验证](development.md) 中的命令单独验收，具体未完成项见 [本地验收交接](handoffs/2026-10-25-local-validation.md)。

## 常见问题

| 现象 | 检查 |
| --- | --- |
| Python 版本不满足依赖 | 检查 `poetry run python --version`，通过 `poetry env use` 选择 >=3.11 |
| 页面打开但 API 连接失败 | 确认后端在 8001，前端启动或构建时设置了 `VITE_API_URL` |
| 5173 端口已占用 | 停止本项目旧前端进程，或同时调整前端端口及 `FRONTEND_ORIGINS` |
| Analyze 提示缺少模型 key / 模型未就绪 | 检查登录用户 Settings、供应商和模型名，或 Ollama 服务与实际标签 |
| 缺少当前报价、新闻或其他证据 | 检查 Finnhub key、网络与数据权限；Yahoo 日线不覆盖所有证据 |
| 用户 key 解密失败 | 恢复原来的 `APP_ENCRYPTION_KEY`，或在 Settings 重新保存用户 key |
| PostgreSQL 连接失败 | 确认 Docker 已启动、容器健康、5433 端口和 DATABASE_URL 密码正确；不会退回 SQLite |
| 老数据库报缺少列 | 停止服务、备份，再检查迁移状态并按第 3 节升级 |

## 当前功能入口

左侧保留 Home、Watchlist、Screener、Scanner、Analyze、Reports、Paper、Backtest。独立 Sectors 和 Institutional 页面已移除；原 Lab 标签会在重新加载后迁移为 Backtest。

- **Backtest（基础版）**：创建策略，选择自己的 watchlist 或指数股票池，设置历史区间、入场规则、止损、初始资金、手续费和滑点；保存参数后运行。无需模型 key，历史行情仍需网络。高级 JSON 编辑器保留额外策略规则。图表通过带登录鉴权的请求获取。尚未连接 Analyze 策略，不支持运行进度、取消任务或参数对比。
- **Paper（开发中，暂不开放）**：侧栏仅显示状态，不可进入；个人 Paper API 未挂载。以下为保留原型的能力，不能作为当前用户操作步骤：创建自己的虚拟 USD 账户，设置初始资金，再记录模拟买入/卖出、更新手动估值、查看持仓和成交。每个用户独立，拒绝资金不足、超卖和非有限数值。首版使用**手动输入的模拟价格**，不自动下单，不声称是实时行情或真实券商成交；不计手续费、无杠杆和卖空。尚无自动报价、挂单撮合、资金曲线和策略自动执行。

个人 Paper 表为 `user_paper_accounts`、`user_paper_positions`、`user_paper_trades`，迁移版本 `c6d9e2f4a810`。旧全局 `paper_*` 历史保留，不会显示给普通用户，也不会转换成任意用户的账户。旧 host book 定时任务默认关闭，仅显式设置 `ENABLE_HOST_PAPER_JOBS=true` 才启用，与个人 Paper 账户无关。

## 安装完成后检查

1. `/health` 返回正常，页面可以注册、退出并重新登录。
2. 创建自己的 watchlist，刷新页面后记录仍在，说明账户数据已保存到 PostgreSQL。
3. Paper 应显示“开发中”，没有开户、买卖或估值操作入口。
4. Backtest 先选择少量股票的 watchlist，保存日期与规则，再运行并查看结果和图表。
5. 配置用户模型后单独测试 Analyze；没有模型时不把完整 AI 报告算作已验收。

本地已验证 PostgreSQL 登录与个人 Paper、真实 Yahoo 历史回测及无 MongoDB 路径。真实模型报告质量和生产部署仍需各自验收，详见 [当前交接记录](handoffs/2026-10-28-postgres-local.md)。
