"""Small LLM-call helper for the research pipeline.

Why a separate helper instead of reusing src/utils/llm.py:call_llm?
The legacy helper extracts model config from AgentState (the LangGraph
state used by src/agents/). The research pipeline has its own state
shape and doesn't need that coupling. This helper takes raw prompts +
pydantic models and uses the DeepSeek default that matches the
production cron's cost target (~$0.0005/call).

Override via env vars RESEARCH_MODEL_NAME / RESEARCH_MODEL_PROVIDER for
local experimentation.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Callable, TypeVar

from pydantic import BaseModel
from src.llm.models import get_model

logger = logging.getLogger(__name__)

_T = TypeVar("_T", bound=BaseModel)

_DEFAULT_MODEL = "deepseek-chat"
_DEFAULT_PROVIDER = "DeepSeek"


# Phase 10.5 fix: bilingual H2 heading map. Used by sections to localize
# their hardcoded English markdown heading when report_language=='zh'.
SECTION_HEADING_ZH: dict[str, str] = {
    "## Macro Regime":                     "## 宏观环境",
    "## Sector and Peer Comparison":       "## 行业与同业比较",
    "## Company Fundamentals":             "## 公司基本面",
    "## Financial Statement Review":       "## 财务报表回顾",
    "## Valuation Analysis":               "## 估值分析",
    "## Technical Analysis":               "## 技术分析",
    "## Risk and Position Sizing":         "## 风险与仓位管理",
    "## Event Risk Check":                 "## 事件风险检查",
    "## Final Conditional Strategy":       "## 最终条件性策略",
    "## Executive Summary":                "## 执行摘要",
    "## Evidence Ledger":                  "## 证据账本",
    "## Conviction Score":                 "## 信念 / 配置质量评分",
    "## Conviction / Setup Quality Score": "## 信念 / 配置质量评分",
    "## Bear / Base / Bull Scenarios":     "## 熊 / 基准 / 牛 情景",
    "## Bear/Base/Bull Scenarios":         "## 熊 / 基准 / 牛 情景",
    "## Debate Summary":                   "## 辩论纪要",
    "## Data Health":                      "## 数据健康度",
    "## Missing Data":                     "## 缺失数据 / 低置信领域",
}


def localized_heading(heading: str, lang: str) -> str:
    """Swap a hardcoded English '## Foo' heading to Chinese when lang=='zh'."""
    if lang == "zh":
        return SECTION_HEADING_ZH.get(heading, heading)
    return heading


def today_context(scan_date: str | None) -> str:
    """Phase 10.5 fix: tell the LLM today's date so it doesn't lean on its
    training cutoff. Returns '' when scan_date is missing/falsy."""
    if not scan_date:
        return ""
    return (
        f"CONTEXT: Today is {scan_date}. All analysis MUST reflect "
        f"current information as of this date. Do NOT default to older "
        f"data from your training cutoff -- when in doubt about recent "
        f"events, say so explicitly rather than invent stale facts.\n\n"
    )


def language_instruction(lang: str) -> str:
    """Phase 7 i18n — produce a system-prompt fragment instructing the LLM
    to respond in the given language. Empty string for 'en' (no-op default).

    Placed LAST in the prompt chain (after persona prepends) so it's the
    most recent instruction the LLM sees — empirically the strongest
    compliance lever for DeepSeek/OpenAI.
    """
    if lang == "zh":
        return (
            "=== 强制语言要求 (LANGUAGE REQUIREMENT — HARD RULE) ===\n"
            "你必须用 简体中文 输出 全部 内容。这不是建议、不是默认偏好,是\n"
            "硬性要求。具体要求:\n"
            "  1. 所有段落文字 — 中文。不要写 'For NVIDIA, the question is...'\n"
            "     要写 '对 NVIDIA 而言, 问题是...'\n"
            "  2. 所有 H2 / H3 / H4 标题 — 中文。不要写 '### Core investment\n"
            "     question' 要写 '### 核心投资问题'。不要写 '### Moat and\n"
            "     competitors' 要写 '### 护城河与竞争对手'。不要写 '### Risk\n"
            "     factors' 要写 '### 风险因素'.\n"
            "  3. 所有 **粗体标签** — 中文。不要写 '**Valuation Verdict**:' 要写\n"
            "     '**估值结论**:'。不要写 '**Bottom Line**:' 要写 '**底线**:'.\n"
            "  4. 所有表头单元格 — 中文。不要写 '| Metric | Value |' 要写\n"
            "     '| 指标 | 数值 |'.\n"
            "  5. 所有列表项标签 — 中文。bullet 列表里的 '**Confidence**:'\n"
            "     必须写成 '**置信度**:'.\n"
            "保留不动的内容:\n"
            "  - 股票代码 (NVDA / 600519.SH / AAPL)\n"
            "  - 货币符号 ($ / ¥ / €)\n"
            "  - 数字、百分比、技术指标名 (RSI / MACD / KDJ / Bollinger / ATR\n"
            "    / SMA20 / EBITDA / DCF)\n"
            "  - 公司英文全名首次出现时 (如 NVIDIA Corporation), 之后用简称.\n"
            "\n"
            "示例 — 正确的 H3 翻译:\n"
            "  Core investment question -> 核心投资问题\n"
            "  Business and segment map -> 业务与分部地图\n"
            "  Industry structure       -> 行业结构\n"
            "  Moat and competitors     -> 护城河与竞争对手\n"
            "  Strategic catalysts      -> 战略催化剂\n"
            "  Management and capital allocation -> 管理层与资本配置\n"
            "  Thesis breakers and variant view  -> 论点破坏因素与异议\n"
            "  Evidence gaps and confidence      -> 证据缺口与置信度\n"
            "  Valuation Verdict        -> 估值结论\n"
            "  Current Market Inputs    -> 当前市场输入\n"
            "  Relative Valuation       -> 相对估值\n"
            "  Sensitivity and Margin of Safety -> 敏感性与安全边际\n"
            "  Backtest Validation      -> 回测验证\n"
            "  Implications for NVDA    -> 对 NVDA 的影响\n"
            "  Index Trend / Sector bias / Stop width — 也翻译.\n"
            "\n"
            "如果你写出任何一个英文 H3 / 英文 strong 标签 / 英文段落, 输出就\n"
            "是不合格的。最后检查一遍, 任何英文字 (除上面允许的代码/符号)\n"
            "都要改成中文.\n"
            "=== 结束语言要求 ===\n\n"
        )
    return ""


def _schema_hint(pydantic_model: type[BaseModel]) -> str:
    """Produce a one-liner-per-field schema hint for the LLM."""
    schema = pydantic_model.model_json_schema()
    props = schema.get("properties", {})
    if not props:
        return "Respond as a JSON object."
    lines = ["Respond as a JSON object with these exact fields:"]
    for name, info in props.items():
        desc = info.get("description", "")
        type_hint = info.get("type", "string")
        if desc:
            lines.append(f'  "{name}" ({type_hint}): {desc}')
        else:
            lines.append(f'  "{name}" ({type_hint})')
    return "\n".join(lines)


def call_research_llm(
    prompt,
    pydantic_model: type[_T],
    *,
    max_retries: int = 3,
    default_factory: Callable[[], _T] | None = None,
) -> _T:
    """Call the LLM with structured output. Retry on parse/transient
    errors up to ``max_retries``. If all retries fail and
    ``default_factory`` is provided, return its result; otherwise
    re-raise the last exception.

    ``prompt`` can be anything the LangChain ``invoke`` accepts — a
    string, a ChatPromptTemplate, a message list. Callers usually
    pre-format into a string for simplicity.
    """
    model_name = os.environ.get("RESEARCH_MODEL_NAME", _DEFAULT_MODEL)
    model_provider = os.environ.get("RESEARCH_MODEL_PROVIDER", _DEFAULT_PROVIDER)

    llm = get_model(model_name, model_provider)
    structured = llm.with_structured_output(pydantic_model, method="json_mode")

    # DeepSeek (and other json_mode providers) require:
    #   (a) the prompt to contain the literal word "json"
    #   (b) field-name hints, because json_mode does NOT share the
    #       pydantic schema with the model — without hints DeepSeek
    #       invents field names like {"summary": ...} when we expected
    #       {"narrative": ...}.
    # We append a concrete schema hint listing the expected fields and
    # their descriptions. Structured prompts (ChatPromptTemplate /
    # message lists) are left alone — advanced callers handle this
    # themselves.
    if isinstance(prompt, str):
        hint = _schema_hint(pydantic_model)
        prompt = prompt + "\n\n" + hint

    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return structured.invoke(prompt)
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "call_research_llm attempt %d/%d failed: %s",
                attempt + 1, max_retries, exc,
            )
            if attempt < max_retries - 1:
                time.sleep(0.5 * (attempt + 1))

    if default_factory is not None:
        logger.warning("call_research_llm exhausted retries; using default_factory")
        return default_factory()
    assert last_exc is not None
    raise last_exc
