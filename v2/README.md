# v2 数据与量化模块

v2 已被当前应用使用，不是尚未集成的独立原型。

- data/：DataClient 协议、数据适配器、工厂与按能力路由。
- scanner/：事件检测、评分和扫描执行。
- pipeline/：扫描与旧 LangGraph 投资分析之间的编排。
- signals/、event_study/、backtesting/、validation/：量化信号与评估工具，数据可得性和 point-in-time 限制需逐路径核对。
- self_evolve/、scanner/evolve/：研究与离线策略评估工具。
- portfolio/optimizer.py、risk/manager.py、pipeline/execution.py 为未实现的占位文件，不承诺提供优化、风控和成交模拟能力。

默认 provider 优先可选 MongoDB 缓存，在线回退到 Yahoo 日线与 Finnhub 当前数据。FD 显式兼容入口保留；DataClient 边界继续供检测器、Lab 和回测复用。[确认需求](../docs/requirements/market-data-and-analyze.md) · [Scanner](scanner/README.md)
