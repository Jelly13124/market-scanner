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
- relative_volume：当日成交量 ≥ 此前 20 根日线均量的 2 倍；方向取决于当日涨跌，平盘为中性且方向分为 0。
- range_breakout：复权收盘价严格突破/跌破此前 20 根日线收盘价区间，不含当日；固定带符号 severity 为 ±2。
- relative_strength：相同 20 个交易日内相对 SPY 涨幅差达到 ±5 个百分点；每达到阈值一倍计 2 分，绝对值上限 5。

新增三个检测器只依赖 Yahoo 日线，可无 Finnhub key、无 MongoDB 运行。缺数据返回 None；相对强弱要求两边日期匹配。盘中最新日线和成交量尚未完成，建议收盘后运行。每天满足条件都会触发，暂无冷却或 AND/OR 组合。UI 的倍率用于排序，不改变触发阈值；窗口/阈值目前仅支持 Python 构造参数。新增 severity 是排序量尺而非统计 z-score。显式选择检测器的旧配置需手动勾选新增项；选择全部的配置自动包含它们。

部分旧类仍可导入，但没有注册；不要把文件存在等同于默认启用。LEGACY_DETECTOR_ALIASES 和 RETIRED_DETECTORS 用于读取旧保存配置，不应随文档清理删除。

## 数据与错误语义

当前数据工厂仍为旧 hybrid；新目标见 [需求基线](../../docs/requirements/market-data-and-analyze.md)。缺少数据返回 None；已完成但没事件返回 triggered=False。数据源权限错误不可理解为市场没有机会。

规则、线程隔离和静态检查见 [开发说明](../../docs/development.md)。Quant overlay 当前默认权重为 0；如重新启用，需要确认数据能力与独立验证，不能假定当前财务快照是历史 point-in-time 数据。

## 使用与验证

在项目环境运行 `python -m v2.scanner --help` 查看当前 CLI 参数。当前 CLI 的 hybrid key 检查尚未适配新方案，不表示 MongoDB 历史入口已实现。

离线测试：`poetry run pytest v2/scanner tests/test_detector_invariants.py -q`。真实 API smoke 必须显式启用，先限定标的和范围，避免无意触发付费或全市场抓取。
