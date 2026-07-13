"""Search endpoint tests — the DB FALLBACK path, exercised with NO Elasticsearch.

With ELASTICSEARCH_URL unset (the conftest env never sets it), es_enabled() is
False and GET /api/tracker/search must fall back to a case-insensitive substring
match on title/company, stay user-scoped, and return all apps for an empty query.
Also asserts the ES helpers are inert / non-fatal when ES is disabled.
"""
import uuid

from fastapi.testclient import TestClient

from src.server import app
from src.services import search as es_search

client = TestClient(app)


def _register():
    email = f"user-{uuid.uuid4().hex[:10]}@example.com"
    r = client.post(
        "/api/auth/register", json={"email": email, "password": "hunter2pw"}
    )
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _seed(token, title, company):
    r = client.post(
        "/api/tracker", headers=_auth(token), json={"title": title, "company": company}
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_es_disabled_by_default():
    # The test env sets no ELASTICSEARCH_URL, so ES is off and the fallback runs.
    assert es_search.es_enabled() is False


def test_search_requires_auth():
    assert client.get("/api/tracker/search?q=acme").status_code == 401


def test_search_fallback_substring_case_insensitive():
    token = _register()
    _seed(token, "Backend Engineer", "Acme Corp")
    _seed(token, "Data Scientist", "Globex")
    _seed(token, "Platform Engineer", "acme labs")  # lowercase company

    r = client.get("/api/tracker/search?q=acme", headers=_auth(token))
    assert r.status_code == 200, r.text
    companies = {a["company"] for a in r.json()}
    # Both "Acme Corp" and "acme labs" match case-insensitively; Globex does not.
    assert companies == {"Acme Corp", "acme labs"}


def test_search_matches_title_too():
    token = _register()
    _seed(token, "Kubernetes Platform Engineer", "Initech")
    _seed(token, "Frontend Developer", "Initech")

    r = client.get("/api/tracker/search?q=kubernetes", headers=_auth(token))
    assert r.status_code == 200
    titles = [a["title"] for a in r.json()]
    assert titles == ["Kubernetes Platform Engineer"]


def test_search_empty_query_returns_all_newest_first():
    token = _register()
    id1 = _seed(token, "First Role", "Co A")
    id2 = _seed(token, "Second Role", "Co B")

    r = client.get("/api/tracker/search?q=", headers=_auth(token))
    assert r.status_code == 200
    ids = [a["id"] for a in r.json()]
    assert ids == [id2, id1]  # newest first

    # Missing q param behaves the same as empty.
    r2 = client.get("/api/tracker/search", headers=_auth(token))
    assert [a["id"] for a in r2.json()] == [id2, id1]


def test_search_is_user_scoped():
    token_a = _register()
    token_b = _register()
    _seed(token_a, "Secret Acme Role", "AcmeSecret")

    # B searches the same term and must never see A's app.
    r = client.get("/api/tracker/search?q=acme", headers=_auth(token_b))
    assert r.status_code == 200
    assert r.json() == []

    # A still finds it.
    r = client.get("/api/tracker/search?q=acme", headers=_auth(token_a))
    assert [a["title"] for a in r.json()] == ["Secret Acme Role"]


def test_search_no_matches_returns_empty():
    token = _register()
    _seed(token, "Backend Engineer", "Acme")
    r = client.get("/api/tracker/search?q=nonexistentxyz", headers=_auth(token))
    assert r.status_code == 200
    assert r.json() == []


def test_index_and_delete_are_noops_when_es_disabled():
    # These must never raise when ES is off (they guard on es_enabled()).
    es_search.index_app(type("Row", (), {"id": 1, "user_id": 1, "title": "t",
                                         "company": "c", "status": "applied",
                                         "payload": None})())
    es_search.delete_app(1)


def test_search_apps_raises_sentinel_when_disabled():
    import pytest

    with pytest.raises(es_search.SearchUnavailable):
        es_search.search_apps(1, "acme")
