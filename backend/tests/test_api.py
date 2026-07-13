"""Smoke tests that run without a Groq key (no LLM calls)."""
import io

from docx import Document
from fastapi.testclient import TestClient
from src.server import app
from src.services.skillmatch import skill_match

client = TestClient(app)


def _docx_bytes(*paragraphs):
    doc = Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


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


def test_analyze_requires_both_fields():
    r = client.post("/api/analyze", json={"jd_text": "Backend engineer", "cv_text": " "})
    assert r.status_code == 400


def test_parse_resume_docx_ok():
    data = _docx_bytes(
        "Jane Developer",
        "Shipped FastAPI services serving 2M requests/day",
    )
    r = client.post(
        "/api/parse-resume",
        files={"file": ("resume.docx", data,
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert r.status_code == 200
    text = r.json()["text"]
    assert "Jane Developer" in text
    assert "FastAPI" in text


def test_parse_resume_rejects_unsupported_type():
    r = client.post(
        "/api/parse-resume",
        files={"file": ("resume.txt", b"just some text", "text/plain")},
    )
    assert r.status_code == 400
    assert "PDF or DOCX" in r.json()["detail"]


def test_parse_resume_rejects_oversize():
    # A .pdf name so the type check passes; oversize check should fire first.
    big = b"%PDF-1.4" + b"0" * (2 * 1024 * 1024 + 1)
    r = client.post(
        "/api/parse-resume",
        files={"file": ("big.pdf", big, "application/pdf")},
    )
    assert r.status_code == 400
    assert "too large" in r.json()["detail"].lower()


def test_parse_resume_empty_extraction():
    # Valid-named DOCX but empty content -> near-empty text -> 400, not 500.
    data = _docx_bytes("")
    r = client.post(
        "/api/parse-resume",
        files={"file": ("empty.docx", data,
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert r.status_code == 400


def test_parse_resume_corrupt_pdf_is_400_not_500():
    r = client.post(
        "/api/parse-resume",
        files={"file": ("broken.pdf", b"not really a pdf", "application/pdf")},
    )
    assert r.status_code == 400


# ---- deterministic skill-match signal (no LLM) ----
def test_skill_match_covers_present_flags_missing():
    result = skill_match(
        ["Python", "Kubernetes"],
        "Python developer with FastAPI",
    )
    covered = {c["requirement"] for c in result["covered"]}
    assert "Python" in covered
    assert "Kubernetes" in result["missing"]
    assert result["coverage_score"] == 50
    assert result["method"] == "keyword term coverage"
    # covered scores are rounded similarities in [0, 1]
    for c in result["covered"]:
        assert 0.0 <= c["score"] <= 1.0


def test_skill_match_is_deterministic():
    reqs = ["Python", "PostgreSQL", "Kafka"]
    cv = "Backend engineer using Python and PostgreSQL"
    assert skill_match(reqs, cv) == skill_match(reqs, cv)


def test_skill_match_empty_inputs_do_not_crash():
    assert skill_match([], "some cv text") == {
        "coverage_score": 0,
        "covered": [],
        "missing": [],
        "method": "keyword term coverage",
    }
    empty_cv = skill_match(["Python"], "")
    assert empty_cv["coverage_score"] == 0
    assert empty_cv["covered"] == []
    assert empty_cv["missing"] == ["Python"]
