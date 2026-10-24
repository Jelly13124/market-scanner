"""WebhookHandler tests — httpx.Client mocked.

We test the contract:
  * 2xx → ok, 4xx → error with no retry, 5xx → 1 retry then error
  * Auth header forwarded when set, omitted when None
  * Payload includes the expected PipelineRun fields
  * SSRF guard rejects internal targets (and lets allow_local=True through)
  * Timeout returns an error result (no raise)
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from app.backend.services.notifications.webhook_handler import WebhookHandler


def _sub(target: str = "https://hooks.example.com/in/abc", auth: str | None = None):
    return SimpleNamespace(
        id=1, channel="webhook", target=target, label=None,
        enabled=True, event_type="pipeline.completed", auth_header=auth,
    )


def _run():
    return SimpleNamespace(
        id="abc123", scan_date="2026-05-18", template="quick",
        top_n=3, universe="nasdaq100", status="COMPLETE",
        duration_seconds=12.0,
        watchlist_json=[{"ticker": "AAPL"}],
        agent_decisions_json={"AAPL": {"action": "buy", "quantity": 1}},
        analyst_signals_json={},
    )


def _mock_client(status_codes: list[int], body: str = ""):
    """A MagicMock httpx.Client where successive .post() calls return
    each status_code in order."""
    client = MagicMock(spec=httpx.Client)
    responses = []
    for sc in status_codes:
        r = MagicMock(spec=httpx.Response)
        r.status_code = sc
        r.text = body
        responses.append(r)
    client.post.side_effect = responses
    return client


class TestSuccessAndAuth:
    def test_2xx_is_ok(self):
        client = _mock_client([200])
        h = WebhookHandler(http_client=client, allow_local=True)
        result = h.send(_sub(), _run())
        assert result["status"] == "ok"
        assert result["http_code"] == 200
        assert client.post.call_count == 1

    def test_auth_header_forwarded_when_set(self):
        client = _mock_client([200])
        h = WebhookHandler(http_client=client, allow_local=True)
        h.send(_sub(auth="Bearer xyz"), _run())
        sent_headers = client.post.call_args.kwargs["headers"]
        assert sent_headers["Authorization"] == "Bearer xyz"

    def test_auth_header_omitted_when_none(self):
        client = _mock_client([200])
        h = WebhookHandler(http_client=client, allow_local=True)
        h.send(_sub(auth=None), _run())
        sent_headers = client.post.call_args.kwargs["headers"]
        assert "Authorization" not in sent_headers

    def test_payload_shape(self):
        client = _mock_client([200])
        h = WebhookHandler(http_client=client, allow_local=True)
        h.send(_sub(), _run())
        payload = client.post.call_args.kwargs["json"]
        assert payload["event"] == "pipeline.completed"
        assert payload["run_id"] == "abc123"
        assert payload["template"] == "quick"
        assert payload["agent_decisions"]["AAPL"]["action"] == "buy"


class TestRetryLogic:
    def test_4xx_no_retry(self):
        client = _mock_client([404], body="not found")
        h = WebhookHandler(http_client=client, allow_local=True,
                           retry_sleep_seconds=0.0)
        result = h.send(_sub(), _run())
        assert result["status"] == "error"
        assert result["http_code"] == 404
        assert client.post.call_count == 1

    def test_5xx_then_2xx_succeeds(self):
        client = _mock_client([503, 200])
        h = WebhookHandler(http_client=client, allow_local=True,
                           retry_sleep_seconds=0.0)
        result = h.send(_sub(), _run())
        assert result["status"] == "ok"
        assert result["http_code"] == 200
        assert client.post.call_count == 2

    def test_5xx_twice_returns_error(self):
        client = _mock_client([503, 502], body="busy")
        h = WebhookHandler(http_client=client, allow_local=True,
                           retry_sleep_seconds=0.0)
        result = h.send(_sub(), _run())
        assert result["status"] == "error"
        assert result["http_code"] == 502
        assert client.post.call_count == 2


class TestTimeoutAndConnect:
    def test_timeout_returns_error(self):
        client = MagicMock(spec=httpx.Client)
        client.post.side_effect = httpx.TimeoutException("read timeout")
        h = WebhookHandler(http_client=client, allow_local=True,
                           retry_sleep_seconds=0.0)
        result = h.send(_sub(), _run())
        assert result["status"] == "error"
        assert "timeout" in result["error_text"].lower()
        # Both attempts consumed.
        assert client.post.call_count == 2

    def test_connect_error_returns_error(self):
        client = MagicMock(spec=httpx.Client)
        client.post.side_effect = httpx.ConnectError("DNS failed")
        h = WebhookHandler(http_client=client, allow_local=True,
                           retry_sleep_seconds=0.0)
        result = h.send(_sub(), _run())
        assert result["status"] == "error"
        assert "DNS failed" in result["error_text"]


class TestSSRFGuard:
    def test_rejects_localhost_by_default(self):
        client = MagicMock(spec=httpx.Client)
        h = WebhookHandler(http_client=client, allow_local=False)
        result = h.send(_sub(target="http://127.0.0.1:8001/hook"), _run())
        assert result["status"] == "error"
        assert "internal" in result["error_text"].lower()
        client.post.assert_not_called()

    def test_rejects_rfc1918(self):
        client = MagicMock(spec=httpx.Client)
        h = WebhookHandler(http_client=client, allow_local=False)
        result = h.send(_sub(target="http://192.168.1.50/x"), _run())
        assert result["status"] == "error"
        client.post.assert_not_called()

    def test_rejects_non_http_scheme(self):
        client = MagicMock(spec=httpx.Client)
        h = WebhookHandler(http_client=client, allow_local=True)
        result = h.send(_sub(target="file:///etc/passwd"), _run())
        assert result["status"] == "error"
        assert "scheme" in result["error_text"].lower()
        client.post.assert_not_called()

    def test_allow_local_lets_localhost_through(self):
        client = _mock_client([200])
        h = WebhookHandler(http_client=client, allow_local=True)
        result = h.send(_sub(target="http://127.0.0.1:8001/hook"), _run())
        assert result["status"] == "ok"
        client.post.assert_called_once()
