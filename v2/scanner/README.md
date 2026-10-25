# Scanner 当前行为

Scanner 是事件预筛选器，用于找出值得进一步分析的标的；触发事件不等于已证明的方向性交易信号。

## 当前启用检测器

注册表以 detectors/__init__.py 的 ALL_DETECTORS 为准：

- earnings_event：财报前后催化窗口。
- insider_cluster：内部人交易聚集。
- intraday_move：日内涨跌、跳空与振幅。
- analyst_rating：评级行动变化。
- target_price_change：本地逐日分析师目标价快照变化，至少两份快照。
- bollinger_squeeze：布林带收窄。
- rsi_divergence：价格与 RSI 背离。
- ma_cross：均线交叉。

部分旧类仍可导入，但没有注册；不要把文件存在等同于默认启用。LEGACY_DETECTOR_ALIASES 和 RETIRED_DETECTORS 用于读取旧保存配置，不应随文档清理删除。

## 数据与错误语义

当前数据工厂仍为旧 hybrid；新目标见 [需求基线](../../docs/requirements/market-data-and-analyze.md)。缺少数据返回 None；已完成但没事件返回 triggered=False。数据源权限错误不可理解为市场没有机会。

规则、线程隔离和静态检查见 [开发说明](../../docs/development.md)。Quant overlay 当前默认权重为 0；如重新启用，需要确认数据能力与独立验证，不能假定当前财务快照是历史 point-in-time 数据。

## 使用与验证

在项目环境运行 `python -m v2.scanner --help` 查看当前 CLI 参数。当前 CLI 的 hybrid key 检查尚未适配新方案，不表示 MongoDB 历史入口已实现。

离线测试：`poetry run pytest v2/scanner tests/test_detector_invariants.py -q`。真实 API smoke 必须显式启用，先限定标的和范围，避免无意触发付费或全市场抓取。
