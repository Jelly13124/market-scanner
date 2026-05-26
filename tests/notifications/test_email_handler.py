"""EmailHandler tests — Resend API mocked via injected httpx.Client."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from app.backend.services.notifications.email_handler import EmailHandler


def _fake_subscription(target: str = "user@example.com"):
    return SimpleNamespace(
        id=1, channel="email", target=target, label="test",
        enabled=True, event_type="pipeline.completed", auth_header=None,
    )


def _fake_run():
    return SimpleNamespace(
        id="abc123def456",
        scan_date="2026-05-18",
        template="quick",
        duration_seconds=12.0,
        agent_decisions_json={"AAPL": {"action": "buy", "quantity": 1, "confidence": 80}},
        analyst_signals_json={},
    )


def _mock_client(response_status: int = 200, response_json: dict | None = None):
    """Return a MagicMock httpx.Client that returns a single canned response."""
    client = MagicMock(spec=httpx.Client)
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = response_status
    resp.json.return_value = response_json or {"id": "msg_xyz"}
    resp.text = ""
    client.post.return_value = resp
    return client


class TestSendSuccess:
    def test_ok_path(self):
        client = _mock_client(200, {"id": "msg_xyz"})
        handler = EmailHandler(api_key="re_test", http_client=client)
        result = handler.send(_fake_subscription(), _fake_run())
        assert result["status"] == "ok"
        assert result["http_code"] == 200
        assert result["message_id"] == "msg_xyz"
        assert result["error_text"] is None
        assert result["latency_ms"] >= 0

    def test_posts_to_resend_endpoint(self):
        client = _mock_client(200)
        handler = EmailHandler(api_key="re_test", http_client=client)
        handler.send(_fake_subscription(), _fake_run())
        url = client.post.call_args[0][0]
        assert url == "https://api.resend.com/emails"

    def test_sends_bearer_auth_header(self):
        client = _mock_client(200)
        handler = EmailHandler(api_key="re_secret_xyz", http_client=client)
        handler.send(_fake_subscription(), _fake_run())
        kwargs = client.post.call_args.kwargs
        assert kwargs["headers"]["Authorization"] == "Bearer re_secret_xyz"

    def test_payload_includes_html_and_text(self):
        client = _mock_client(200)
        handler = EmailHandler(api_key="re_test", http_client=client)
        handler.send(_fake_subscription("recipient@x.com"), _fake_run())
        payload = client.post.call_args.kwargs["json"]
        assert payload["to"] == ["recipient@x.com"]
        assert payload["from"]  # defaulted to sandbox
        assert "Pipeline" in payload["subject"]
        assert "2026-05-18" in payload["subject"]
        # HTML + text both present so clients can pick.
        assert "<html" in payload["html"]
        assert "AAPL" in payload["html"]
        assert "AAPL" in payload["text"]

    def test_uses_custom_from_address(self):
        client = _mock_client(200)
        handler = EmailHandler(
            api_key="re_test", from_address="alerts@mydomain.com",
            http_client=client,
        )
        handler.send(_fake_subscription(), _fake_run())
        payload = client.post.call_args.kwargs["json"]
        assert payload["from"] == "alerts@mydomain.com"


class TestSendFailure:
    def test_missing_api_key_returns_error_without_calling_resend(self, monkeypatch):
        # Explicitly clear the env var — the dev .env may have a real key
        # and the handler falls back to ``os.getenv("RESEND_API_KEY")`` when
        # ``api_key=None`` is passed.
        monkeypatch.delenv("RESEND_API_KEY", raising=False)
        client = MagicMock(spec=httpx.Client)
        handler = EmailHandler(api_key=None, http_client=client)
        result = handler.send(_fake_subscription(), _fake_run())
        assert result["status"] == "error"
        assert "RESEND_API_KEY" in result["error_text"]
        client.post.assert_not_called()

    def test_4xx_response_returns_error(self):
        client = _mock_client(401, {
            "name": "missing_api_key", "message": "API key invalid",
        })
        handler = EmailHandler(api_key="re_bad", http_client=client)
        result = handler.send(_fake_subscription(), _fake_run())
        assert result["status"] == "error"
        assert result["http_code"] == 401
        assert "missing_api_key" in result["error_text"]
        assert "API key invalid" in result["error_text"]

    def test_5xx_response_returns_error(self):
        client = _mock_client(503, {"name": "internal", "message": "Try again"})
        handler = EmailHandler(api_key="re_test", http_client=client)
        result = handler.send(_fake_subscription(), _fake_run())
        assert result["status"] == "error"
        assert result["http_code"] == 503

    def test_httpx_timeout_returns_error(self):
        client = MagicMock(spec=httpx.Client)
        client.post.side_effect = httpx.TimeoutException("read timeout")
        handler = EmailHandler(api_key="re_test", http_client=client)
        result = handler.send(_fake_subscription(), _fake_run())
        assert result["status"] == "error"
        assert "timeout" in result["error_text"].lower()
        assert result["http_code"] is None

    def test_generic_http_error_returns_error(self):
        client = MagicMock(spec=httpx.Client)
        client.post.side_effect = httpx.ConnectError("DNS failure")
        handler = EmailHandler(api_key="re_test", http_client=client)
        result = handler.send(_fake_subscription(), _fake_run())
        assert result["status"] == "error"
        assert "DNS failure" in result["error_text"]
