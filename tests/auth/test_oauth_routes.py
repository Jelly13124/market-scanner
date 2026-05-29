import app.backend.routes.auth as auth_routes


def test_authorize_redirects_with_state(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "gid")
    r = client.get("/auth/oauth/google", follow_redirects=False)
    assert r.status_code == 302
    assert "accounts.google.com" in r.headers["location"]
    assert client.cookies.get("oauth_state") is not None


def test_callback_creates_user_and_redirects(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "gid")
    client.get("/auth/oauth/google", follow_redirects=False)
    state = client.cookies.get("oauth_state")
    monkeypatch.setattr(auth_routes, "exchange_code", lambda provider, code, redirect_uri: {"provider_account_id": "g1", "email": "a@x.com", "full_name": "A", "email_verified": True})
    r = client.get(f"/auth/oauth/google/callback?code=abc&state={state}", follow_redirects=False)
    assert r.status_code == 302 and "access_token=" in r.headers["location"]


def test_callback_rejects_unverified_email(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "gid")
    client.get("/auth/oauth/google", follow_redirects=False)
    state = client.cookies.get("oauth_state")
    monkeypatch.setattr(auth_routes, "exchange_code", lambda provider, code, redirect_uri: {"provider_account_id": "g1", "email": "a@x.com", "full_name": "A", "email_verified": False})
    r = client.get(f"/auth/oauth/google/callback?code=abc&state={state}", follow_redirects=False)
    assert r.status_code == 400


def test_callback_bad_state(client):
    r = client.get("/auth/oauth/google/callback?code=abc&state=wrong", follow_redirects=False)
    assert r.status_code == 400
