"""Webhook delivery — POST PipelineRun JSON payload to subscription.target.

Generic outbound HTTP — the user configures the URL plus an optional
``auth_header`` (full header value e.g. ``Bearer xxxx`` or a HMAC
signature). Built for Slack/Discord/Zapier/personal endpoints.

Safety:
  * 10s connect+read timeout (one daily run mustn't be blocked by a
    flaky downstream).
  * 1 retry on 5xx after a 2s sleep; 4xx never retries (caller error).
  * SSRF guard: rejects RFC1918 / loopback / link-local URLs unless
    ``NOTIFICATIONS_ALLOW_LOCAL=1`` is set in env (set to "1" for local
    dev when testing against http://127.0.0.1:NNNN).

Like ``EmailHandler``, never raises — returns a result dict the
dispatcher records as a NotificationDelivery row.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import socket
import time
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)


class WebhookHandler:
    """One-shot webhook POSTer."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 10.0,
        retry_sleep_seconds: float = 2.0,
        allow_local: bool | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._timeout = timeout_seconds
        self._retry_sleep = retry_sleep_seconds
        if allow_local is None:
            allow_local = os.getenv("NOTIFICATIONS_ALLOW_LOCAL", "").lower() in ("1", "true", "yes")
        self._allow_local = allow_local
        self._http = http_client

    def send(self, subscription: Any, run: Any) -> dict[str, Any]:
        """POST run payload to subscription.target. Returns result dict.

        Keys: status ('ok'|'error'), http_code (int|None), error_text
        (str|None), latency_ms (int).
        """
        t0 = time.monotonic()
        target = subscription.target

        # SSRF guard
        guard_err = self._reject_internal_target(target)
        if guard_err:
            return _error_result(None, guard_err, t0)

        event_type = getattr(subscription, "event_type", "pipeline.completed")
        payload = _build_payload(run, event_type=event_type)
        headers = {"Content-Type": "application/json", "User-Agent": "ai-hedge-fund/1"}
        if subscription.auth_header:
            headers["Authorization"] = subscription.auth_header

        # 1 retry on 5xx; 4xx returns immediately.
        last_resp: httpx.Response | None = None
        last_err: Exception | None = None
        for attempt in (1, 2):
            try:
                client = self._http or httpx.Client(timeout=self._timeout)
                try:
                    resp = client.post(target, json=payload, headers=headers)
                finally:
                    if self._http is None:
                        client.close()
                last_resp = resp
                if 200 <= resp.status_code < 300:
                    return _ok_result(resp.status_code, t0)
                if 400 <= resp.status_code < 500:
                    return _error_result(
                        resp.status_code, _summarize(resp), t0,
                    )
                # 5xx — retry once.
                if attempt == 1:
                    time.sleep(self._retry_sleep)
                    continue
                return _error_result(resp.status_code, _summarize(resp), t0)
            except httpx.TimeoutException as e:
                last_err = e
                if attempt == 1:
                    time.sleep(self._retry_sleep)
                    continue
                return _error_result(None, f"timeout: {e}", t0)
            except httpx.HTTPError as e:
                last_err = e
                if attempt == 1:
                    time.sleep(self._retry_sleep)
                    continue
                return _error_result(
                    None, f"http error: {type(e).__name__}: {e}", t0,
                )
            except Exception as e:
                # Defensive — payload build is the most likely culprit.
                logger.exception("WebhookHandler.send unexpected error")
                return _error_result(None, f"{type(e).__name__}: {e}", t0)

        # Should be unreachable; guard for type-checker.
        if last_resp is not None:
            return _error_result(last_resp.status_code, _summarize(last_resp), t0)
        return _error_result(None, f"unknown failure: {last_err}", t0)

    # ------------------------------------------------------------------
    # SSRF guard
    # ------------------------------------------------------------------

    def _reject_internal_target(self, target: str) -> str | None:
        """Return error string if the URL resolves to a private/loopback
        address (and ``allow_local`` is off), else None.

        We only check the hostname literal — DNS-rebinding attacks would
        need a per-request socket-level check which is overkill for a
        single-user local tool. The literal check catches the common
        footguns (http://localhost, http://192.168.x.y, http://10.x.y.z).
        """
        try:
            parsed = urlparse(target)
        except Exception:
            return f"invalid URL: {target!r}"
        # Scheme check applies regardless of allow_local — file://, gopher://
        # etc. are never useful targets even on a dev box.
        if parsed.scheme not in ("http", "https"):
            return f"only http/https allowed; got scheme={parsed.scheme!r}"
        host = parsed.hostname
        if not host:
            return f"URL missing hostname: {target!r}"
        # Past basic shape checks — if user opted into local targets, skip
        # the private-range check.
        if self._allow_local:
            return None
        # If host parses as an IP, check ranges directly. Otherwise resolve
        # the hostname; treat resolution failure as a soft pass (the POST
        # itself will fail anyway, and we don't want to block legitimate
        # transient DNS hiccups here).
        try:
            ip = ipaddress.ip_address(host)
            if _is_internal(ip):
                return f"refusing to POST to internal address {host} (set NOTIFICATIONS_ALLOW_LOCAL=1 to override)"
            return None
        except ValueError:
            pass
        # Hostname — resolve and check.
        try:
            infos = socket.getaddrinfo(host, None)
        except OSError:
            return None  # let httpx report it
        for info in infos:
            try:
                ip = ipaddress.ip_address(info[4][0])
            except ValueError:
                continue
            if _is_internal(ip):
                return f"refusing to POST to internal address {host} → {ip} (set NOTIFICATIONS_ALLOW_LOCAL=1 to override)"
        return None


def _is_internal(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_loopback or ip.is_private or ip.is_link_local
        or ip.is_multicast or ip.is_unspecified
    )


# ----------------------------------------------------------------------
# Payload + result helpers
# ----------------------------------------------------------------------


def _build_payload(run: Any, event_type: str = "pipeline.completed") -> dict[str, Any]:
    """Mirror the shape of PipelineRunDetail so consumers see the same
    JSON the frontend sees via GET /pipeline/runs/{id}. Extra: include
    ``gist_map`` (LLM-generated per-ticker take) when the dispatcher
    attached one — useful for downstream Slack/Discord templates that
    want a one-liner instead of the full PM reasoning."""
    return {
        "event": event_type,
        "run_id": getattr(run, "id", None),
        "scan_date": getattr(run, "scan_date", None),
        "template": getattr(run, "template", None),
        "top_n": getattr(run, "top_n", None),
        "universe": getattr(run, "universe", None),
        "status": getattr(run, "status", None),
        "duration_seconds": getattr(run, "duration_seconds", None),
        "watchlist": getattr(run, "watchlist_json", None)
                     or getattr(run, "watchlist", None),
        "agent_decisions": getattr(run, "agent_decisions_json", None)
                           or getattr(run, "agent_decisions", None),
        "analyst_signals": getattr(run, "analyst_signals_json", None)
                           or getattr(run, "analyst_signals", None),
        "gist_map": getattr(run, "gist_map", None) or {},
    }


def _ok_result(http_code: int, t0: float) -> dict[str, Any]:
    return {
        "status": "ok",
        "http_code": http_code,
        "error_text": None,
        "latency_ms": int((time.monotonic() - t0) * 1000),
    }


def _error_result(http_code: int | None, msg: str, t0: float) -> dict[str, Any]:
    return {
        "status": "error",
        "http_code": http_code,
        "error_text": msg[:1000],
        "latency_ms": int((time.monotonic() - t0) * 1000),
    }


def _summarize(resp: httpx.Response) -> str:
    text = (resp.text or "")[:300]
    return f"HTTP {resp.status_code}: {text}" if text else f"HTTP {resp.status_code}"
