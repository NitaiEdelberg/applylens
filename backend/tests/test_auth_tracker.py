"""Auth + per-user cloud tracker tests (temp SQLite, no external DB, no LLM).

Covers: register -> login -> token; tracker CRUD scoped to the owner; a second
user cannot read/modify the first user's app; and the keepalive endpoint.
"""
import uuid

from fastapi.testclient import TestClient
from src.server import app

client = TestClient(app)


def _unique_email():
    return f"user-{uuid.uuid4().hex[:10]}@example.com"


def _register(email=None, password="hunter2pw"):
    email = email or _unique_email()
    r = client.post("/api/auth/register", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == email
    return email, password, body["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_register_then_login_returns_token():
    email, password, token = _register()
    assert token
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    assert r.json()["token"]


def test_register_duplicate_email_conflicts():
    email, password, _ = _register()
    r = client.post("/api/auth/register", json={"email": email, "password": password})
    assert r.status_code == 409


def test_login_wrong_password_401():
    email, _, _ = _register()
    r = client.post("/api/auth/login", json={"email": email, "password": "wrongpass"})
    assert r.status_code == 401


def test_tracker_requires_auth():
    assert client.get("/api/tracker").status_code == 401
    assert client.post("/api/tracker", json={"title": "x"}).status_code == 401


def test_tracker_crud_is_user_scoped():
    _, _, token = _register()

    # create
    payload = {"fit": {"overall_score": 88}, "note": "roundtrips"}
    r = client.post(
        "/api/tracker",
        headers=_auth(token),
        json={
            "title": "Backend Engineer",
            "company": "Acme",
            "score": 88,
            "flagged": 2,
            "payload": payload,
        },
    )
    assert r.status_code == 200, r.text
    app_obj = r.json()
    app_id = app_obj["id"]
    assert app_obj["title"] == "Backend Engineer"
    assert app_obj["payload"] == payload  # JSON blob round-trips

    # list (newest first)
    r = client.get("/api/tracker", headers=_auth(token))
    assert r.status_code == 200
    ids = [a["id"] for a in r.json()]
    assert app_id in ids

    # patch status
    r = client.patch(
        f"/api/tracker/{app_id}", headers=_auth(token), json={"status": "interviewing"}
    )
    assert r.status_code == 200
    assert r.json()["status"] == "interviewing"

    # delete
    r = client.delete(f"/api/tracker/{app_id}", headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # gone
    r = client.get("/api/tracker", headers=_auth(token))
    assert app_id not in [a["id"] for a in r.json()]


def test_user_b_cannot_access_user_a_app():
    _, _, token_a = _register()
    _, _, token_b = _register()

    r = client.post(
        "/api/tracker",
        headers=_auth(token_a),
        json={"title": "A's secret role", "company": "SecretCo"},
    )
    assert r.status_code == 200
    app_id = r.json()["id"]

    # B's list never shows A's app
    r = client.get("/api/tracker", headers=_auth(token_b))
    assert app_id not in [a["id"] for a in r.json()]

    # B cannot read/patch/delete A's app -> 404 (not 403, don't leak existence)
    assert client.patch(
        f"/api/tracker/{app_id}", headers=_auth(token_b), json={"status": "offer"}
    ).status_code == 404
    assert client.delete(f"/api/tracker/{app_id}", headers=_auth(token_b)).status_code == 404

    # A still owns it
    assert app_id in [a["id"] for a in client.get("/api/tracker", headers=_auth(token_a)).json()]


def test_invalid_token_is_401():
    assert client.get("/api/tracker", headers=_auth("garbage.token.value")).status_code == 401


def test_keepalive_ok():
    r = client.get("/api/keepalive")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


# ---- account deletion (D4) ----
def _account(email="delete-me@example.com", password="hunter2hunter2"):
    client.post("/api/auth/register", json={"email": email, "password": password})
    token = client.post("/api/auth/login",
                        json={"email": email, "password": password}).json()["token"]
    return token, {"Authorization": "Bearer " + token}


def test_deleting_an_account_takes_the_saved_analyses_with_it():
    token, headers = _account("gone@example.com")
    client.post("/api/tracker", json={"title": "Role A", "company": "Acme"}, headers=headers)
    client.post("/api/tracker", json={"title": "Role B", "company": "Acme"}, headers=headers)
    assert len(client.get("/api/tracker", headers=headers).json()) == 2

    result = client.delete("/api/account", headers=headers)
    assert result.status_code == 200
    assert result.json()["deleted_applications"] == 2

    # The token is now for a user that no longer exists.
    assert client.get("/api/tracker", headers=headers).status_code == 401


def test_the_email_is_free_again_after_deletion():
    email = "reuse@example.com"
    _, headers = _account(email)
    client.delete("/api/account", headers=headers)
    again = client.post("/api/auth/register", json={"email": email, "password": "hunter2hunter2"})
    assert again.status_code == 200, "deleted means deleted, not reserved forever"


def test_deleting_an_account_needs_to_be_signed_in():
    assert client.delete("/api/account").status_code == 401


def test_one_persons_deletion_does_not_touch_another():
    _, mine = _account("mine@example.com")
    _, theirs = _account("theirs@example.com")
    client.post("/api/tracker", json={"title": "Theirs"}, headers=theirs)
    client.delete("/api/account", headers=mine)
    assert len(client.get("/api/tracker", headers=theirs).json()) == 1


def test_the_privacy_policy_is_served_from_the_code():
    policy = client.get("/api/privacy").json()
    assert policy["delete_everything"] == "DELETE /api/account"
    assert "Groq" in " ".join(policy["third_parties"])
