import os
from urllib.parse import urlencode

import httpx

PROVIDERS = {
    "google": {
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://openidconnect.googleapis.com/v1/userinfo",
        "scope": "openid email profile",
    },
    "github": {
        "authorize_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "userinfo_url": "https://api.github.com/user",
        "emails_url": "https://api.github.com/user/emails",
        "scope": "read:user user:email",
    },
}

_CLIENT_IDS = {
    "google": lambda: os.getenv("GOOGLE_CLIENT_ID", ""),
    "github": lambda: os.getenv("GITHUB_CLIENT_ID", ""),
}

_CLIENT_SECRETS = {
    "google": lambda: os.getenv("GOOGLE_CLIENT_SECRET", ""),
    "github": lambda: os.getenv("GITHUB_CLIENT_SECRET", ""),
}


def get_provider(name: str) -> dict:
    if name not in PROVIDERS:
        raise ValueError(f"Unknown OAuth provider: {name!r}")
    return PROVIDERS[name]


def build_authorize_url(provider: str, state: str, redirect_uri: str) -> str:
    cfg = get_provider(provider)
    params = {
        "client_id": _CLIENT_IDS[provider](),
        "redirect_uri": redirect_uri,
        "scope": cfg["scope"],
        "state": state,
        "response_type": "code",
    }
    if provider == "google":
        params["access_type"] = "offline"
    return cfg["authorize_url"] + "?" + urlencode(params)


def exchange_code(provider: str, code: str, redirect_uri: str) -> dict:
    cfg = get_provider(provider)
    client_id = _CLIENT_IDS[provider]()
    client_secret = _CLIENT_SECRETS[provider]()

    token_resp = httpx.post(
        cfg["token_url"],
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        headers={"Accept": "application/json"},
        timeout=15,
    )
    token_resp.raise_for_status()
    access_token = token_resp.json()["access_token"]

    userinfo_resp = httpx.get(
        cfg["userinfo_url"],
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    userinfo_resp.raise_for_status()
    userinfo = userinfo_resp.json()

    if provider == "google":
        return {
            "provider_account_id": str(userinfo["sub"]),
            "email": userinfo.get("email"),
            "full_name": userinfo.get("name"),
            "email_verified": bool(userinfo.get("email_verified")),
        }

    # GitHub: fetch primary email with verified flag from emails endpoint
    emails_resp = httpx.get(
        cfg["emails_url"],
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    emails_resp.raise_for_status()
    emails = emails_resp.json()

    primary = next((e for e in emails if e.get("primary")), None)
    email = primary["email"] if primary else None
    email_verified = bool(primary.get("verified")) if primary else False

    return {
        "provider_account_id": str(userinfo["id"]),
        "email": email,
        "full_name": userinfo.get("name") or userinfo.get("login"),
        "email_verified": email_verified,
    }
