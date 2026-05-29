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
