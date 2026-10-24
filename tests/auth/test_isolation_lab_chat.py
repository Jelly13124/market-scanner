"""Isolation tests: lab chat messages are scoped by owning strategy's user_id."""

from tests.auth.conftest import auth_header

_STRATEGY = {"name": "Chat Strategy", "description": "test"}


def test_chat_isolation(full_client, two_users):
    a, b = two_users

    # A creates a strategy
    r = full_client.post("/lab/strategies", json=_STRATEGY, headers=auth_header(a))
    assert r.status_code == 201, r.text
    sid = r.json()["id"]

    # B cannot list chat messages under A's strategy → 404
    assert full_client.get(f"/lab/strategies/{sid}/chat", headers=auth_header(b)).status_code == 404

    # B cannot post a chat message to A's strategy → 404
    assert full_client.post(
        f"/lab/strategies/{sid}/chat",
        json={"message": "hijack"},
        headers=auth_header(b),
    ).status_code == 404

    # A can post a message. Wave B1 gates /lab chat on the configured provider
    # key (mirrors /research/analyze), so seed A's DEEPSEEK key first.
    from unittest.mock import patch
    from src.lab.chat import ChatReply, ChatResponse

    seed = full_client.post(
        "/api-keys/",
        json={"provider": "DEEPSEEK_API_KEY", "key_value": "sk-a-deepseek"},
        headers=auth_header(a),
    )
    assert seed.status_code == 200, seed.text

    with patch("app.backend.routes.lab.run_chat_turn") as mock_chat:
        mock_chat.return_value = ChatResponse(root=ChatReply(message="OK"))
        r2 = full_client.post(
            f"/lab/strategies/{sid}/chat",
            json={"message": "hello"},
            headers=auth_header(a),
        )
    assert r2.status_code == 200, r2.text

    # A can list their chat
    msgs = full_client.get(f"/lab/strategies/{sid}/chat", headers=auth_header(a))
    assert msgs.status_code == 200
    assert len(msgs.json()) >= 1

    # B still cannot see A's messages
    assert full_client.get(f"/lab/strategies/{sid}/chat", headers=auth_header(b)).status_code == 404


def test_chat_requires_auth(full_client, two_users):
    a, _ = two_users
    r = full_client.post("/lab/strategies", json=_STRATEGY, headers=auth_header(a))
    sid = r.json()["id"]
    assert full_client.get(f"/lab/strategies/{sid}/chat").status_code == 401
    assert full_client.post(f"/lab/strategies/{sid}/chat", json={"message": "hi"}).status_code == 401
