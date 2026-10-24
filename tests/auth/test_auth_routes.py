def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_register_login_me_flow(client):
    r = client.post("/auth/register", json={"email": "a@x.com", "password": "pw123456", "full_name": "A"})
    assert r.status_code == 201
    tok = r.json()["access_token"]
    me = client.get("/auth/me", headers=_auth(tok))
    assert me.status_code == 200 and me.json()["email"] == "a@x.com"


def test_register_duplicate_409(client):
    client.post("/auth/register", json={"email": "a@x.com", "password": "pw123456"})
    assert client.post("/auth/register", json={"email": "a@x.com", "password": "pw123456"}).status_code == 409


def test_login_bad_password(client):
    client.post("/auth/register", json={"email": "a@x.com", "password": "pw123456"})
    assert client.post("/auth/login", json={"email": "a@x.com", "password": "nope"}).status_code == 401


def test_me_requires_auth(client):
    assert client.get("/auth/me").status_code == 401


def test_refresh_issues_new_access(client):
    client.post("/auth/register", json={"email": "a@x.com", "password": "pw123456"})
    login = client.post("/auth/login", json={"email": "a@x.com", "password": "pw123456"})
    # refresh cookie is set on the client jar by login
    r = client.post("/auth/refresh")
    assert r.status_code == 200 and "access_token" in r.json()


def test_refresh_token_rejected_as_access(client):
    # A refresh token must NOT authenticate /me (type-confusion guard).
    client.post("/auth/register", json={"email": "a@x.com", "password": "pw123456"})
    login = client.post("/auth/login", json={"email": "a@x.com", "password": "pw123456"})
    refresh_tok = login.cookies.get("refresh_token")
    assert refresh_tok is not None
    assert client.get("/auth/me", headers=_auth(refresh_tok)).status_code == 401


def test_short_password_rejected(client):
    r = client.post("/auth/register", json={"email": "b@x.com", "password": "short"})
    assert r.status_code == 422  # min_length=8 enforced by RegisterRequest


def test_me_default_timezone(client):
    r = client.post("/auth/register", json={"email": "a@x.com", "password": "pw123456"})
    tok = r.json()["access_token"]
    me = client.get("/auth/me", headers=_auth(tok))
    assert me.status_code == 200 and me.json()["timezone"] == "America/New_York"


def test_patch_me_updates_timezone(client):
    r = client.post("/auth/register", json={"email": "a@x.com", "password": "pw123456"})
    tok = r.json()["access_token"]
    patched = client.patch("/auth/me", headers=_auth(tok), json={"timezone": "Asia/Shanghai"})
    assert patched.status_code == 200 and patched.json()["timezone"] == "Asia/Shanghai"
    # Persisted: a fresh /me reflects it.
    assert client.get("/auth/me", headers=_auth(tok)).json()["timezone"] == "Asia/Shanghai"


def test_patch_me_rejects_unknown_timezone(client):
    r = client.post("/auth/register", json={"email": "a@x.com", "password": "pw123456"})
    tok = r.json()["access_token"]
    bad = client.patch("/auth/me", headers=_auth(tok), json={"timezone": "Mars/Phobos"})
    assert bad.status_code == 400


def test_patch_me_requires_auth(client):
    assert client.patch("/auth/me", json={"timezone": "UTC"}).status_code == 401
