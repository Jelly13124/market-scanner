"""Email delivery via Resend REST API.

We call Resend's ``POST /emails`` endpoint directly with ``httpx`` rather
than pulling in the ``resend`` SDK — the endpoint is one line and avoiding
the SDK keeps our dep tree slim. See https://resend.com/docs/api-reference/emails/send-email.

Config (env vars):
  RESEND_API_KEY      — required; obtained from https://resend.com → API Keys.
  RESEND_FROM_EMAIL   — optional; defaults to Resend's sandbox sender
                        ``onboarding@resend.dev``. Without a verified
                        sending domain, the sandbox sender can only
                        deliver to the email registered on your Resend
                        account.

The handler never raises — it returns a result dict the dispatcher
records as a NotificationDelivery row.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

from app.backend.services.notifications.bundled_email import (
    render_bundled_research_html, render_bundled_research_text,
)
from app.backend.services.notifications.render import (
    render_pipeline_html, render_pipeline_text,
    render_research_html, render_research_text,
)

logger = logging.getLogger(__name__)


RESEND_API_URL = "https://api.resend.com/emails"
DEFAULT_FROM = "onboarding@resend.dev"


class EmailHandler:
    """One-shot Resend sender. Cheap to construct (no persistent state)."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        from_address: str | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key or os.getenv("RESEND_API_KEY")
        self._from = from_address or os.getenv("RESEND_FROM_EMAIL") or DEFAULT_FROM
        # Allow tests to inject a mocked httpx.Client; in production we
        # build a fresh short-lived client per send so connections don't
        # linger across the (~daily) cron.
        self._http = http_client

    def send(self, subscription: Any, run: Any) -> dict[str, Any]:
        """Render + POST to Resend. Return a delivery result dict.

        Keys: status ('ok'|'error'), http_code (int|None),
        message_id (str|None), error_text (str|None), latency_ms (int).
        """
        t0 = time.monotonic()

        if not self._api_key:
            return _error_result(
                None, "RESEND_API_KEY is not configured", t0,
            )

        try:
            # Route to the appropriate render functions based on event_type.
            # Phase 1: pipeline.completed; Phase 3: research.completed;
            # Phase 5E: research.bundled (run is a list[ResearchReport]).
            event_type = getattr(subscription, "event_type", "pipeline.completed")
            subject = _make_subject(run, event_type=event_type)
            if event_type == "research.bundled":
                html_body = render_bundled_research_html(run)
                text_body = render_bundled_research_text(run)
            elif event_type == "research.completed":
                html_body = render_research_html(run)
                text_body = render_research_text(run)
            elif event_type == "screener.match":
                from app.backend.services.notifications.render import (
                    render_screener_match_html,
                    render_screener_match_text,
                )
                html_body = render_screener_match_html(run)
                text_body = render_screener_match_text(run)
            else:
                # Dispatcher attaches a precomputed gist_map (LLM-generated
                # per-ticker Chinese take) when available. Render handles
                # None / partial map transparently.
                gist_map = getattr(run, "gist_map", None)
                html_body = render_pipeline_html(run, gist_map=gist_map)
                text_body = render_pipeline_text(run)
            payload = {
                "from": self._from,
                "to": [subscription.target],
                "subject": subject,
                "html": html_body,
                "text": text_body,
            }
            headers = {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            }

            client = self._http or httpx.Client(timeout=15.0)
            try:
                resp = client.post(RESEND_API_URL, json=payload, headers=headers)
            finally:
                if self._http is None:
                    client.close()

            latency_ms = int((time.monotonic() - t0) * 1000)
            if 200 <= resp.status_code < 300:
                try:
                    data = resp.json()
                except Exception:
                    data = {}
                return {
                    "status": "ok",
                    "http_code": resp.status_code,
                    "message_id": data.get("id"),
                    "error_text": None,
                    "latency_ms": latency_ms,
                }
            else:
                # Resend returns JSON error bodies with `message` + `name`.
                err_text = _summarize_resend_error(resp)
                return {
                    "status": "error",
                    "http_code": resp.status_code,
                    "message_id": None,
                    "error_text": err_text,
                    "latency_ms": latency_ms,
                }
        except httpx.TimeoutException as e:
            return _error_result(None, f"timeout: {e}", t0)
        except httpx.HTTPError as e:
            return _error_result(None, f"http error: {type(e).__name__}: {e}", t0)
        except Exception as e:
            # Renderer should not raise but guard anyway.
            logger.exception("EmailHandler.send unexpected error")
            return _error_result(None, f"{type(e).__name__}: {e}", t0)


def _make_subject(run: Any, *, event_type: str = "pipeline.completed") -> str:
    # Phase 5E — bundled subject reads len(reports) + the first report's
    # scan_date (all reports in a bundle share the scan date).
    if event_type == "research.bundled":
        reports = run if isinstance(run, list) else []
        n = len(reports)
        scan_date = getattr(reports[0], "scan_date", "—") if reports else "—"
        return f"[ai-hedge-fund] Daily SOP — {scan_date} — {n} tickers"
    if event_type == "screener.match":
        p = run if isinstance(run, dict) else getattr(run, "payload", {}) or {}
        preset_name = p.get("preset_name") or "screener"
        return f"[ai-hedge-fund] Screener match: {preset_name}"
    template = getattr(run, "template", "—")
    scan_date = getattr(run, "scan_date", "—")
    agent_decisions = (
        getattr(run, "agent_decisions_json", None)
        or getattr(run, "agent_decisions", None)
        or {}
    )
    n = len(agent_decisions)
    return f"[ai-hedge-fund] Pipeline {template} — {scan_date} — {n} decisions"


def _summarize_resend_error(resp: httpx.Response) -> str:
    """Compact 1-line error suitable for the delivery audit log."""
    try:
        data = resp.json()
        name = data.get("name") or "unknown_error"
        msg = data.get("message") or ""
        return f"{name}: {msg}"[:1000]
    except Exception:
        text = (resp.text or "")[:500]
        return f"HTTP {resp.status_code}: {text}"


def _error_result(http_code: int | None, msg: str, t0: float) -> dict[str, Any]:
    return {
        "status": "error",
        "http_code": http_code,
        "message_id": None,
        "error_text": msg,
        "latency_ms": int((time.monotonic() - t0) * 1000),
    }
