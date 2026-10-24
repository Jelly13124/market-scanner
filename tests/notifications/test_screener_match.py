"""screener.match render + dispatch tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.backend.services.notifications.render import (
    render_screener_match_html,
    render_screener_match_text,
)


def _payload():
    return {
        "preset_name": "cheap tech",
        "match_count": 2,
        "preset_id": 7,
        "snapshot_date": "2026-05-28",
        "rows": [
            {"ticker": "AAPL", "price": "210", "pe_ttm": "32", "change_pct": "0.01"},
            {"ticker": "JPM", "price": "180", "pe_ttm": "11", "change_pct": "-0.02"},
        ],
    }


def test_render_html_has_preset_and_tickers():
    h = render_screener_match_html(_payload())
    assert "cheap tech" in h and "AAPL" in h and "JPM" in h and "<table" in h.lower()


def test_render_text_plain():
    t = render_screener_match_text(_payload())
    assert "cheap tech" in t and "AAPL" in t


def test_render_never_raises_sparse():
    render_screener_match_html({"preset_name": "x", "rows": [{"ticker": "Z"}]})
    render_screener_match_text({"preset_name": "x", "rows": [{"ticker": "Z"}]})


def test_render_html_via_surrogate_object():
    """render_screener_match_html also accepts a surrogate object with .payload."""
    from types import SimpleNamespace

    surrogate = SimpleNamespace(payload=_payload())
    h = render_screener_match_html(surrogate)
    assert "cheap tech" in h and "AAPL" in h


def test_dispatch_screener_match_sends_to_enabled_subs():
    from app.backend.services.notifications.dispatcher import NotificationDispatcher

    email = MagicMock()
    email.send.return_value = {
        "status": "ok",
        "http_code": None,
        "error_text": None,
        "latency_ms": 1,
    }
    disp = NotificationDispatcher(
        session_factory=MagicMock(),
        email_handler=email,
        webhook_handler=MagicMock(),
    )
    fake_sub = MagicMock(id=1, channel="email", event_type="screener.match")
    with (
        patch(
            "app.backend.services.notifications.dispatcher.SubscriptionRepository"
        ) as SR,
        patch(
            "app.backend.services.notifications.dispatcher._snapshot",
            side_effect=lambda s: s,
        ),
        patch(
            "app.backend.services.notifications.dispatcher.DeliveryRepository"
        ),
    ):
        SR.return_value.list_enabled_for_event.return_value = [fake_sub]
        n = disp.dispatch_screener_match(payload=_payload())
    assert n == 1
    assert email.send.called


def test_dispatch_screener_match_returns_zero_when_no_subs():
    from app.backend.services.notifications.dispatcher import NotificationDispatcher

    disp = NotificationDispatcher(session_factory=MagicMock())
    with patch(
        "app.backend.services.notifications.dispatcher.SubscriptionRepository"
    ) as SR:
        SR.return_value.list_enabled_for_event.return_value = []
        n = disp.dispatch_screener_match(payload=_payload())
    assert n == 0


def test_dispatch_screener_match_with_owner_uses_scoped_lookup():
    """Wave 6: passing user_id routes through the OWNER-SCOPED subscription
    lookup, never the global one — so a preset match can't notify other
    tenants' channels."""
    from app.backend.services.notifications.dispatcher import NotificationDispatcher

    email = MagicMock()
    email.send.return_value = {
        "status": "ok", "http_code": None, "error_text": None, "latency_ms": 1,
    }
    disp = NotificationDispatcher(
        session_factory=MagicMock(),
        email_handler=email,
        webhook_handler=MagicMock(),
    )
    owner_sub = MagicMock(id=9, channel="email", event_type="screener.match")
    with (
        patch(
            "app.backend.services.notifications.dispatcher.SubscriptionRepository"
        ) as SR,
        patch(
            "app.backend.services.notifications.dispatcher._snapshot",
            side_effect=lambda s: s,
        ),
        patch(
            "app.backend.services.notifications.dispatcher.DeliveryRepository"
        ),
    ):
        SR.return_value.list_enabled_for_event_and_user.return_value = [owner_sub]
        n = disp.dispatch_screener_match(payload=_payload(), user_id=101)

    assert n == 1
    # Scoped path taken with the right owner; global path never touched.
    SR.return_value.list_enabled_for_event_and_user.assert_called_once_with(
        "screener.match", user_id=101
    )
    SR.return_value.list_enabled_for_event.assert_not_called()


def test_existing_events_still_render():
    """Additive guard — pipeline + research renderers still import + run."""
    from app.backend.services.notifications.render import (
        render_pipeline_html,
        render_research_html,
    )

    assert callable(render_pipeline_html) and callable(render_research_html)
