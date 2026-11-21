# Market Scanner 研究闭环 ERD

## PostgreSQL · 业务与来源

实线标记已落地的核心外键，虚线标记后续策略版本和回测关联。图中省略通知、调度和 Paper 等外围模块。

```mermaid
erDiagram
    users ||--o{ api_keys : "保存凭据"
    users ||--o{ user_watchlists : "维护自选股"
    users ||--o{ screener_presets : "保存筛选条件"
    users ||--o{ scanner_configs : "配置扫描"
    user_watchlists |o--o{ scanner_configs : "可用作股票池"
    scanner_configs ||--o{ scan_runs : "执行"
    scan_runs ||--o{ watchlist_entries : "保存入选结果"
    users ||--o{ research_reports : "拥有报告"
    users ||--o{ strategies : "拥有策略"
    strategies ||--o{ backtests : "执行回测"

    universe_snapshots |o--o{ universe_snapshots : "扫描引用最近一次筛选"
    users ||--o{ universe_snapshots : "冻结筛选结果"
    user_watchlists |o--o{ universe_snapshots : "可选来源"
    universe_snapshots |o--o{ scan_runs : "记录实际股票池"
    watchlist_entries |o--o{ research_reports : "提供扫描证据"
    strategies ||..o{ STRATEGY_REVISIONS : "保存确认版本"
    research_reports |o..o{ STRATEGY_REVISIONS : "提供策略草稿"
    universe_snapshots ||..o{ STRATEGY_REVISIONS : "固定回测股票池"
    STRATEGY_REVISIONS |o..o{ backtests : "记录执行版本"

    ticker_snapshots {
        string ticker
        date snapshot_date
    }
    universe_snapshots {
        int id PK
        json filters
        json tickers
        date screener_snapshot_date
        timestamp selected_at
    }
    STRATEGY_REVISIONS {
        int id PK
        json rules_and_parameters
        string engine_version
        timestamp confirmed_at
    }
```

Screener 按交易日读取 ticker_snapshots，表中 ticker 与 snapshot_date 联合唯一。一次筛选可以选中多行，因此股票池快照复制实际选中的代码、日期和条件。现有 watchlist_entries 存储扫描排名结果，与用户手动维护的 user_watchlists 含义不同。新闭环运行必须保存来源；旧运行和独立创建的报告可以缺少相应关联。新运行在 scan_runs.outcomes 保存逐股状态和检测器证据，在 detector_config 保存当次生效的配置与版本。

## MongoDB · 行情、扫描历史与分析证据

以下是仓库 Mongo schema 中的主要集合与应用层文档引用。每个集合的主键是 _id。清单按集合名和文档 ID 指向实际输入版本。

```mermaid
erDiagram
    instruments ||--o{ price_bars : "日线修订"
    instruments }o--o{ news_articles : "新闻涉及标的"
    instruments ||--o{ company_snapshots : "观测快照"
    instruments ||--o{ financial_statements : "财报版本"
    instruments ||--o{ corporate_events : "市场事件"
    instruments ||--o{ data_sync_jobs : "采集范围与状态"
    instruments ||--o{ datasets : "分析标的"
    datasets }o--o{ price_bars : "清单可引用具体修订"
    scan_runs ||--o{ scan_results : "全股票池逐股结果"
    instruments ||--o{ scan_results : "被扫描标的"
    datasets |o--o{ scan_results : "扫描输入"
    scan_results |o--o{ analysis_runs : "触发分析"
    datasets |o--o{ analysis_runs : "分析输入"
    analysis_runs |o--o| reports : "生成报告"
    datasets |o--o{ reports : "保留输入引用"

    price_bars {
        ObjectId instrument_id
        string session_date
        int revision
        decimal adjusted_close
        long volume
        date first_seen_at
        string content_hash
    }
```

同一标的、来源、周期、交易日和修订号共同标识一个日线版本。报告所用行情以具体版本为准。Mongo 中的 scan_runs 和 reports 是历史档案，PostgreSQL 中的同类记录承载用户操作和导航。

拟新增的跨库关系由应用维护。PostgreSQL 回测记录保存 Mongo 冻结数据集的 ID、哈希与完整性状态。当前 datasets 以单一标的为中心，全股票池回测还需要组合级清单，覆盖实际股票列表、预热期、SPY、公司行动和各输入版本。只有原始输入完整且可读时才提供原数据重放。

依据：[SQLAlchemy 模型](../../app/backend/database/models.py) · [MongoDB schema](mongodb-schema.json) · [闭环设计](../superpowers/specs/2026-11-17-history-research-loop-design.md)
