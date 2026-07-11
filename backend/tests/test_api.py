"""Smoke tests that run without a Groq key (no LLM calls)."""
from fastapi.testclient import TestClient
from src.server import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_extract_requires_jd():
    r = client.post("/api/extract", json={"jd_text": "  "})
    assert r.status_code == 400


def test_fit_requires_both_fields():
    r = client.post("/api/fit", json={"jd_text": "Backend engineer", "cv_text": ""})
    assert r.status_code == 400
