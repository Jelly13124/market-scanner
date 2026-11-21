"""Render the signal-time and analysis-time inputs with separate dates."""
from contextvars import ContextVar
from datetime import datetime, timezone

# LangGraph propagates context variables across its section/debate workers.
SIGNAL_PROMPT = ContextVar("scanner_signal_prompt", default="")


def market_evidence(shared, *, observed_at=None):
    """Summarize the actual input bundle. The retrieval time is distinct from the bar date."""
    latest = max(shared.prices, key=lambda p: p.time, default=None)
    return {
        "as_of": shared.scan_date,
        "observed_at": (observed_at or datetime.now(timezone.utc)).isoformat(),
        "price_bars": len(shared.prices),
        "latest_price_session": latest.time[:10] if latest else None,
        "latest_close": latest.close if latest else None,
    }


def evidence_markdown(source, market, language="en"):
    if not source:
        return ""
    zh = language == "zh"
    missing = "未记录" if zh else "unavailable"
    run_id = source.get("scan_run_id") or source.get("mongo_scan_run_id")
    result_id = source.get("scan_result_id") or source.get("mongo_scan_result_id")
    rank = source.get("rank") or missing
    score = source.get("composite_score")
    score_label = f"{score:g}" if score is not None else missing
    identity = (f"扫描 #{run_id} · 结果 #{result_id} · 排名 {rank}" if zh
                else f"Scan #{run_id} · result #{result_id} · rank {rank}")
    lines = [
        "## 原始扫描信号" if zh else "## Original Scanner signal",
        f"{identity} · {source['ticker']} · {source.get('direction') or missing} · "
        + ("综合分 " if zh else "score ") + score_label,
    ]
    lines.append(("扫描开始时间 " if zh else "Scan started at ") + (source.get("scan_started_at") or missing))
    if source.get("scan_as_of"):
        lines.append(("扫描截至 " if zh else "Scan as of ") + str(source["scan_as_of"]))
    results = {item["detector"]: item for item in (source.get("outcome") or {}).get("detector_results", [])}
    definitions = {item["name"]: item for item in (source.get("detector_config") or {}).get("detectors", [])}
    for trigger in source["triggers"]:
        name = trigger["detector"]
        detail = results.get(name, {})
        session = trigger.get("signal_session") or detail.get("signal_session")
        lines.append(f"- {name} · " + ("信号交易日 " if zh else "signal session ") + str(session or missing))
        if trigger.get("asof_date"):
            lines.append(("截至 " if zh else "As of ") + str(trigger["asof_date"]))
        definition = definitions.get(name, {})
        version = detail.get("version") or definition.get("version") or missing
        lines.append(("检测器版本 " if zh else "Detector version ") + str(version))
        if definition.get("description"):
            lines.append(definition["description"])
        parameters = definition.get("parameters")
        if parameters:
            lines.append("执行参数" if zh else "Executed parameters")
            lines.extend(f"- {key} = {value}" for key, value in parameters.items())
        elif parameters is None:
            lines.append("未记录执行参数。" if zh else "Executed parameters unavailable.")
        if trigger.get("direction"):
            lines.append(("触发方向 " if zh else "Trigger direction ") + str(trigger["direction"]))
        if trigger.get("reason"):
            lines.append(str(trigger["reason"]))
        values = dict(trigger.get("components") or {})
        if trigger.get("severity_z") is not None:
            values["severity_z"] = trigger["severity_z"]
        lines.extend(f"- {key} = {value}" for key, value in values.items())
    if not source["triggers"]:
        lines.append("未记录触发明细。" if zh else "Trigger details unavailable.")
    if market:
        lines.extend([
            "## 分析时的市场数据" if zh else "## Analysis market evidence",
            ("读取时间 " if zh else "Inputs read at ") + market["observed_at"],
            ("分析截至 " if zh else "Analysis as of ") + market["as_of"],
            ("最近价格交易日 " if zh else "Latest price session ") + str(market["latest_price_session"] or missing),
            ("收盘价 " if zh else "Close ") + str(market["latest_close"] if market["latest_close"] is not None else missing),
            ("日线根数 " if zh else "Daily bars ") + str(market["price_bars"]),
        ])
    return "\n\n".join(lines)


def analyze_markdown(report):
    request = report.get("request")
    provenance = evidence_markdown(getattr(request, "source_scan_evidence", None),
                                   report.get("analysis_market_evidence"), getattr(request, "report_language", "en"))
    sections = [p.markdown for name, p in report["sections"].items() if not name.startswith("_")]
    return "\n\n".join(([provenance] if provenance else []) + sections)
