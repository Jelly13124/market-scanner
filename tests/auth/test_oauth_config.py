import pytest
from app.backend.auth import oauth


def test_get_provider_known(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "gid"); monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "gsec")
    p = oauth.get_provider("google")
    assert p["authorize_url"].startswith("https://accounts.google.com")


def test_get_provider_unknown():
    with pytest.raises(ValueError):
        oauth.get_provider("facebook")


def test_build_authorize_url(monkeypatch):
    monkeypatch.setenv("GITHUB_CLIENT_ID", "ghid")
    url = oauth.build_authorize_url("github", state="xyz", redirect_uri="http://cb")
    assert "state=xyz" in url and "client_id=ghid" in url and url.startswith("https://github.com/login/oauth/authorize")
