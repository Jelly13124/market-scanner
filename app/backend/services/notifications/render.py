"""HTML + plain-text rendering for pipeline-completion notifications.

Output an email-safe HTML body (inline styles only — Gmail strips
``<style>`` blocks) plus a plain-text alternate. The HTML structure
mirrors what the frontend's ``AgentRunDetail`` dialog renders so the
email feels familiar to the user.

Inputs are the ``PipelineRun`` ORM row (already populated with
``agent_decisions_json`` and ``analyst_signals_json``). Renderers never
touch the DB and never raise — bad/missing fields render as ``—``.
"""

from __future__ import annotations

import html
from typing import Any

# Color palette matched to the frontend ActionPill (agent-run-detail.tsx).
_ACTION_COLORS: dict[str, tuple[str, str]] = {
    # action  : (bg, fg)
    "buy":   ("#dcfce7", "#166534"),  # green-100 / green-800
    "cover": ("#dcfce7", "#166534"),
    "sell":  ("#fee2e2", "#991b1b"),  # red-100 / red-800
    "short": ("#fee2e2", "#991b1b"),
    "hold":  ("#f3f4f6", "#1f2937"),  # gray-100 / gray-800
}

_SIGNAL_COLORS: dict[str, str] = {
    "bullish": "#16a34a",  # green-600
    "bearish": "#dc2626",  # red-600
    "neutral": "#6b7280",  # gray-500
}


def _esc(v: Any) -> str:
    """HTML-escape; coerce None → empty string."""
    if v is None:
        return ""
    return html.escape(str(v))


def _truncate(text: Any, max_chars: int = 220) -> str:
    s = "" if text is None else str(text)
    return s if len(s) <= max_chars else s[: max_chars - 1] + "…"


def _action_pill(action: str) -> str:
    bg, fg = _ACTION_COLORS.get((action or "").lower(), _ACTION_COLORS["hold"])
    return (
        f'<span style="display:inline-block;padding:2px 8px;border-radius:4px;'
        f'background:{bg};color:{fg};font-weight:700;font-size:11px;'
        f'letter-spacing:0.05em;text-transform:uppercase">{_esc(action or "hold")}</span>'
    )


def _signal_pill(signal: str) -> str:
    color = _SIGNAL_COLORS.get((signal or "").lower(), _SIGNAL_COLORS["neutral"])
    short = {"bullish": "bull", "bearish": "bear", "neutral": "neut"}.get(
        (signal or "").lower(), "neut",
    )
    return (
        f'<span style="color:{color};font-weight:600;font-size:11px">{short}</span>'
    )


def _short_analyst_name(key: str) -> str:
    return (key or "").replace("_agent", "").replace("_", " ")


def _coerce_reasoning_to_text(reasoning: Any) -> str:
    """The frontend handles both string and dict reasoning; email is
    always text. Pick the most useful line if dict."""
    if reasoning is None:
        return ""
    if isinstance(reasoning, str):
        return reasoning
    if isinstance(reasoning, dict):
        # Prefer a key called "reasoning" / "details" if present.
        for k in ("reasoning", "details", "summary"):
            v = reasoning.get(k)
            if isinstance(v, str) and v:
                return v
        # Otherwise: join the top-level signal labels.
        parts = []
        for k, v in reasoning.items():
            if isinstance(v, dict):
                sig = v.get("signal")
                if sig:
                    parts.append(f"{k}={sig}")
        if parts:
            return ", ".join(parts[:6])
    return str(reasoning)[:300]


def render_pipeline_html(
    run: Any,
    *,
    gist_map: dict[str, str] | None = None,
) -> str:
    """Produce an email-safe HTML body for one PipelineRun.

    Accepts the SQLAlchemy ``PipelineRun`` ORM instance (or any object
    with the same attribute names) — we read attributes by name so a
    Pydantic ``PipelineRunDetail`` works too.

    ``gist_map`` (optional): ``{ticker: short Chinese take}`` produced by
    ``notifications.gist.generate_gists``. When present, the per-ticker
    take renders as a highlighted line right under the PM action header.
    Tickers absent from the map render the block exactly as before — so
    a partial gist failure (one ticker missing) degrades gracefully
    instead of breaking the email.
    """
    agent_decisions = getattr(run, "agent_decisions_json", None) or \
        getattr(run, "agent_decisions", None) or {}
    analyst_signals = getattr(run, "analyst_signals_json", None) or \
        getattr(run, "analyst_signals", None) or {}
    tickers = list(agent_decisions.keys())

    template = _esc(getattr(run, "template", "—"))
    scan_date = _esc(getattr(run, "scan_date", "—"))
    duration = getattr(run, "duration_seconds", None)
    duration_str = f"{duration:.1f}s" if isinstance(duration, (int, float)) else "—"
    run_id = _esc(getattr(run, "id", "—"))

    header_html = f'''
    <table cellpadding="0" cellspacing="0" border="0" width="100%"
           style="border-collapse:collapse;font-family:-apple-system,
           BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#111827;
           font-size:14px;line-height:1.4">
      <tr>
        <td style="padding:16px 20px;background:#f9fafb;border-bottom:1px solid #e5e7eb">
          <div style="font-size:18px;font-weight:700;color:#111827">
            Pipeline run — {scan_date}
          </div>
          <div style="margin-top:4px;color:#6b7280;font-size:12px">
            template: <b>{template}</b>
            &nbsp;·&nbsp; duration: <b>{duration_str}</b>
            &nbsp;·&nbsp; {len(tickers)} {"ticker" if len(tickers) == 1 else "tickers"}
            &nbsp;·&nbsp; <span style="font-family:monospace">{run_id[:12]}…</span>
          </div>
        </td>
      </tr>
    </table>
    '''

    if not tickers:
        # Empty watchlist — scanner produced no rows; tell the user.
        return _wrap_email_html(header_html + '''
        <div style="padding:32px 20px;color:#6b7280;font-size:13px;text-align:center;
                    font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif">
          No tickers in this run — the scanner didn't fire on any names today.
        </div>
        ''')

    ticker_blocks: list[str] = []
    for ticker in tickers:
        ticker_blocks.append(_render_ticker_block(
            ticker=ticker,
            decision=agent_decisions.get(ticker, {}),
            analyst_signals=analyst_signals,
            gist=(gist_map or {}).get(ticker),
        ))
    body = "\n".join(ticker_blocks)

    return _wrap_email_html(header_html + body)


# PM directional intent vs valuation_analyst's signal — used to warn when
# the PM is taking a position opposite to what fundamental valuation says.
# (HOLD / SELL / COVER don't conflict — only BUY and SHORT carry directional
# conviction worth flagging against valuation.)
_PM_DIRECTION: dict[str, str] = {
    "buy":   "bullish",
    "short": "bearish",
}


def _valuation_conflict(
    decision: dict[str, Any],
    analyst_signals: dict[str, dict[str, Any]],
    ticker: str,
) -> str | None:
    """Return a Chinese warning sentence if PM action opposes valuation, else None.

    We compare against ``valuation_analyst_agent`` specifically (not the
    other personas) because it's the agent whose mandate is intrinsic
    value vs price — when it disagrees with the PM's directional bet,
    the user wants to see it called out before the wall of analyst rows.
    """
    pm_dir = _PM_DIRECTION.get((decision.get("action") or "").lower())
    if pm_dir is None:
        return None
    val_block = (analyst_signals or {}).get("valuation_analyst_agent") or {}
    val_sig = (val_block.get(ticker) or {}).get("signal")
    if val_sig is None or val_sig == "neutral":
        return None
    if val_sig == pm_dir:
        return None
    # Conflict: PM bullish vs valuation bearish, or vice-versa.
    side = "BUY" if pm_dir == "bullish" else "SHORT"
    val_label = "看空" if val_sig == "bearish" else "看多"
    return f"⚠️ PM 决策 ({side}) vs valuation 信号 ({val_label}) 矛盾"


def _render_ticker_block(
    *,
    ticker: str,
    decision: dict[str, Any],
    analyst_signals: dict[str, dict[str, Any]],
    gist: str | None = None,
) -> str:
    """One ticker — PM action header + optional LLM gist + per-analyst rows."""
    action = decision.get("action", "hold")
    qty = decision.get("quantity", "—")
    conf = decision.get("confidence", None)
    conf_str = f"conf {conf}" if conf is not None else ""
    pm_reasoning = _truncate(decision.get("reasoning"), 320)
    conflict_msg = _valuation_conflict(decision, analyst_signals, ticker)

    pm_block = f'''
    <table cellpadding="0" cellspacing="0" border="0" width="100%"
           style="border-collapse:collapse;margin:20px 0 0 0;
           font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
           border:1px solid #e5e7eb;border-radius:6px;overflow:hidden">
      <tr>
        <td style="padding:10px 16px;background:#f9fafb;border-bottom:1px solid #e5e7eb">
          <span style="font-family:'SF Mono',Consolas,monospace;font-weight:700;
                       font-size:15px;color:#111827">{_esc(ticker)}</span>
          &nbsp; {_action_pill(action)}
          &nbsp; <span style="color:#6b7280;font-size:12px">
                   qty {_esc(qty)} {("· " + conf_str) if conf_str else ""}
                 </span>
        </td>
      </tr>
    '''

    if conflict_msg:
        pm_block += f'''
      <tr>
        <td style="padding:6px 16px;background:#fee2e2;color:#991b1b;
                   font-size:12px;font-weight:600;
                   border-bottom:1px solid #fecaca">
          {_esc(conflict_msg)}
        </td>
      </tr>
        '''

    if gist:
        # LLM-generated 60-char Chinese take. Yellow-tinted background so
        # it visually separates from PM reasoning (which can be in
        # English) without competing with the red conflict bar.
        pm_block += f'''
      <tr>
        <td style="padding:8px 16px;background:#fef3c7;color:#78350f;
                   font-size:12px;font-weight:500;line-height:1.45;
                   border-bottom:1px solid #fde68a">
          <span style="color:#92400e;font-weight:700">💡 Take:</span>
          &nbsp;{_esc(gist)}
        </td>
      </tr>
        '''

    if pm_reasoning:
        pm_block += f'''
      <tr>
        <td style="padding:8px 16px;background:#ffffff;color:#374151;font-size:12px;
                   border-bottom:1px solid #f3f4f6">
          <b style="color:#111827">PM:</b> {_esc(pm_reasoning)}
        </td>
      </tr>
        '''

    # Per-analyst rows
    analyst_rows: list[str] = []
    for analyst_key, ticker_to_sig in (analyst_signals or {}).items():
        sig = (ticker_to_sig or {}).get(ticker)
        if not sig:
            continue
        signal = sig.get("signal", "neutral")
        a_conf = sig.get("confidence", None)
        a_conf_str = f"{a_conf:.0f}" if isinstance(a_conf, (int, float)) else "—"
        a_reasoning = _truncate(_coerce_reasoning_to_text(sig.get("reasoning")), 200)
        analyst_rows.append(f'''
      <tr>
        <td style="padding:6px 16px;border-bottom:1px solid #f3f4f6;color:#4b5563;
                   font-size:12px;vertical-align:top">
          <table cellpadding="0" cellspacing="0" border="0" width="100%"
                 style="border-collapse:collapse">
            <tr>
              <td width="140" style="font-family:'SF Mono',Consolas,monospace;
                                     color:#6b7280;font-size:11px;vertical-align:top">
                {_esc(_short_analyst_name(analyst_key))}
              </td>
              <td width="50" style="vertical-align:top">{_signal_pill(signal)}</td>
              <td width="60" style="color:#6b7280;font-size:11px;
                                    font-variant-numeric:tabular-nums;
                                    vertical-align:top">conf {a_conf_str}</td>
              <td style="color:#374151;font-size:11.5px;vertical-align:top">
                {_esc(a_reasoning) if a_reasoning else ""}
              </td>
            </tr>
          </table>
        </td>
      </tr>
        ''')
    if analyst_rows:
        pm_block += "".join(analyst_rows)

    pm_block += "</table>"
    return pm_block


def _wrap_email_html(inner: str) -> str:
    """Wrap content in a standard responsive container + outer body styles.

    Most email clients strip <html><head> in preview, but kept here so
    forwarded/saved versions render correctly. The max-width = 720 keeps
    layout sensible on phone + desktop.
    """
    return f'''<!doctype html>
<html><head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Pipeline run</title>
</head>
<body style="margin:0;padding:0;background:#f3f4f6">
  <table cellpadding="0" cellspacing="0" border="0" width="100%"
         style="background:#f3f4f6;padding:20px 0">
    <tr>
      <td align="center">
        <table cellpadding="0" cellspacing="0" border="0" width="720"
               style="max-width:720px;width:100%;background:#ffffff;
               border:1px solid #e5e7eb;border-radius:8px;overflow:hidden">
          <tr><td>{inner}</td></tr>
        </table>
      </td>
    </tr>
    <tr>
      <td align="center" style="padding:12px 0;color:#9ca3af;font-size:11px;
                                font-family:-apple-system,BlinkMacSystemFont,sans-serif">
        ai-hedge-fund · automated notification
      </td>
    </tr>
  </table>
</body></html>'''


def render_pipeline_text(run: Any) -> str:
    """Plain-text alternate part (for clients that prefer text).

    Tight, scannable — suitable for an iPhone lock-screen preview as
    well as a fallback for HTML-blocking clients.
    """
    agent_decisions = getattr(run, "agent_decisions_json", None) or \
        getattr(run, "agent_decisions", None) or {}
    template = getattr(run, "template", "—")
    scan_date = getattr(run, "scan_date", "—")

    lines = [
        f"Pipeline run — {scan_date} (template: {template})",
        "=" * 60,
    ]
    if not agent_decisions:
        lines.append("")
        lines.append("(no tickers — scanner didn't fire on any names)")
        return "\n".join(lines)

    for ticker, decision in agent_decisions.items():
        action = (decision.get("action") or "hold").upper()
        qty = decision.get("quantity", "—")
        conf = decision.get("confidence")
        conf_str = f" conf={conf}" if conf is not None else ""
        lines.append("")
        lines.append(f"{ticker:8}  {action:6} qty={qty}{conf_str}")
        reasoning = _truncate(decision.get("reasoning"), 240)
        if reasoning:
            lines.append(f"          {reasoning}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Research report rendering (Phase 3)
# ---------------------------------------------------------------------------


def render_research_html(report) -> str:
    """Email-safe HTML for one ResearchReport row.

    The pipeline pre-rendered the HTML at run time; here we just return
    that string. The fallback handles legacy rows or test fixtures that
    don't carry an HTML payload - wraps the markdown in a minimal
    envelope so the email is never empty.
    """
    html_body = getattr(report, "rendered_html", "") or ""
    if html_body.strip():
        return html_body
    ticker = _esc(getattr(report, "ticker", ""))
    markdown = _esc(getattr(report, "report_markdown", ""))
    return (
        f"<html><body>"
        f"<h1>{ticker}</h1>"
        f"<pre style=\"white-space:pre-wrap;\">{markdown}</pre>"
        f"</body></html>"
    )


def render_research_text(report) -> str:
    """Plain-text alternate part for the email. Strips the markdown
    formatting to a readable plain-text form."""
    markdown = getattr(report, "report_markdown", "") or ""
    # Minimal markdown -> text: drop heading hashes; keep the rest.
    lines = []
    for raw in markdown.split("\n"):
        stripped = raw.lstrip("#").lstrip()
        lines.append(stripped)
    return "\n".join(lines).strip() or f"Research report for {getattr(report, 'ticker', '?')}"
