"""RAG tests — all run with NO API key via the deterministic TF-IDF embedder.

Covers retrieve_context ranking/chunking (pure, no LLM) and an /api/analyze
integration test that mocks the LLM so a tailored bullet can legitimately draw
on a retrieved career-history chunk and be grounded against CV + chunks.
"""
import re

from fastapi.testclient import TestClient

from src import services  # noqa: F401 — ensures package import path
from src.services import rag
from src.server import app

client = TestClient(app)


CAREER_TEXT = """Kubernetes at BigCo: I deployed and scaled production Kubernetes clusters
serving millions of users, owning rollouts and autoscaling for the platform team.

Frontend at SmallCo: built a React dashboard with charts and a design system,
improving load time and accessibility for internal analytics users.

Data pipelines at MidCo: designed batch ETL jobs in Python moving billions of
rows nightly into a warehouse for the analytics organization."""


# ---- retrieve_context: ranking + chunking (TF-IDF, no key, no network) ----
def _force_tfidf(monkeypatch):
    # Force the local embedder regardless of the developer's environment.
    monkeypatch.setattr(rag, "GEMINI_API_KEY", "")


def test_retrieve_ranks_kubernetes_first(monkeypatch):
    _force_tfidf(monkeypatch)
    out = rag.retrieve_context(["Kubernetes", "autoscaling"], CAREER_TEXT, k=4)
    assert out["source"] == "tfidf"
    assert out["chunks"], "expected at least one retrieved chunk"
    # The Kubernetes paragraph is the most relevant to a Kubernetes query.
    assert "Kubernetes" in out["chunks"][0]


def test_retrieve_accepts_string_query(monkeypatch):
    _force_tfidf(monkeypatch)
    out = rag.retrieve_context("React dashboard charts", CAREER_TEXT, k=1)
    assert len(out["chunks"]) == 1
    assert "React" in out["chunks"][0]


def test_retrieve_respects_k(monkeypatch):
    _force_tfidf(monkeypatch)
    out = rag.retrieve_context("Python data pipelines", CAREER_TEXT, k=2)
    assert len(out["chunks"]) == 2


def test_retrieve_empty_career_text(monkeypatch):
    _force_tfidf(monkeypatch)
    out = rag.retrieve_context(["Kubernetes"], "", k=4)
    assert out == {"chunks": [], "source": "tfidf"}


def test_retrieve_drops_tiny_chunks(monkeypatch):
    _force_tfidf(monkeypatch)
    text = "Header\n\n" + "Deployed Kubernetes clusters serving millions of users at BigCo."
    out = rag.retrieve_context("Kubernetes", text, k=4)
    # The 6-char "Header" fragment is dropped; only the real paragraph remains.
    assert len(out["chunks"]) == 1
    assert "Kubernetes" in out["chunks"][0]


def test_default_source_no_key(monkeypatch):
    _force_tfidf(monkeypatch)
    assert rag.default_source() == "tfidf"


# ---- /api/analyze integration with a mocked LLM ----
_CV_RE = re.compile(r'CV:\s*"""(.*?)"""', re.DOTALL)


def _cv_block(prompt: str) -> str:
    m = _CV_RE.search(prompt)
    return m.group(1) if m else ""


def _install_fake_llm(monkeypatch):
    """Patch every service's chat_json with a deterministic, network-free fake.

    The fake reads the CV block from each prompt — which, in the RAG path, is
    (base CV + retrieved chunks) — so the tailor can quote a retrieved chunk and
    the grounder verifies against that same expanded source of truth.
    """

    async def fake(messages, temperature=0.2):
        system = messages[0]["content"]
        user = messages[1]["content"]

        # extract_job
        if "extract structured hiring requirements" in system:
            return {
                "title": "Platform Engineer",
                "seniority": "senior",
                "must_haves": ["Kubernetes", "autoscaling"],
                "nice_to_haves": [],
                "stack": ["Kubernetes"],
            }
        # score_fit
        if "score how well a candidate's CV matches" in system:
            return {"overall_score": 70, "matched": [], "partial": [], "missing": [], "summary": "ok"}
        # tailor: echo a distinctive phrase from the CV block (incl. retrieved chunks)
        if system.startswith("You tailor"):
            cv = _cv_block(user)
            if "Kubernetes" in cv:
                bullet = "Scaled production Kubernetes clusters serving millions of users"
            else:
                bullet = "Built and shipped Python services"
            return {"bullets": [bullet], "cover_letter": ""}
        # grounding: supported iff each long word of the statement is in the CV block
        if "strict fact-checker" in system:
            cv = _cv_block(user).lower()
            import json as _json
            tail = user.split("STATEMENTS:", 1)[1].strip()
            stmts = _json.loads(tail)
            checks = []
            for s in stmts:
                words = [w for w in re.findall(r"[a-zA-Z]+", s.lower()) if len(w) >= 5]
                supported = bool(words) and all(w in cv for w in words)
                checks.append({
                    "statement": s,
                    "supported": supported,
                    "evidence": "CV" if supported else None,
                    "issue": None if supported else "not in CV",
                })
            return {"checks": checks}
        # extract_claims (cover letter is empty here, so this rarely fires)
        if "extract, from a cover letter" in system:
            return {"claims": []}
        return {}

    for mod in ("extract", "fit", "tailor", "grounding"):
        monkeypatch.setattr(f"src.services.{mod}.chat_json", fake)


def test_analyze_with_career_text_uses_rag_and_grounds(monkeypatch):
    _force_tfidf(monkeypatch)
    _install_fake_llm(monkeypatch)

    base_cv = "Backend engineer. Built Python and FastAPI services. Skills: Python, FastAPI, REST."
    r = client.post(
        "/api/analyze",
        json={
            "jd_text": "Senior Platform Engineer needing Kubernetes and autoscaling.",
            "cv_text": base_cv,
            "career_text": CAREER_TEXT,
        },
    )
    assert r.status_code == 200
    data = r.json()

    # RAG engaged and surfaced the Kubernetes experience.
    assert data["rag"]["used"] is True
    assert data["rag"]["source"] == "tfidf"
    assert any("Kubernetes" in c for c in data["rag"]["chunks"])

    # The tailored bullet drew on the retrieved chunk...
    bullets = data["tailor"]["bullets"]
    assert any("Kubernetes" in b for b in bullets)
    # ...and is legitimately GROUNDED against CV + retrieved chunks (not flagged),
    # even though "Kubernetes" is absent from the base CV.
    assert "Kubernetes" not in base_cv
    assert data["tailor"]["flagged_count"] == 0
    assert all(g["supported"] for g in data["tailor"]["grounding"])


def test_analyze_without_career_text_rag_unused(monkeypatch):
    _force_tfidf(monkeypatch)
    _install_fake_llm(monkeypatch)

    r = client.post(
        "/api/analyze",
        json={
            "jd_text": "Senior Platform Engineer needing Kubernetes.",
            "cv_text": "Backend engineer. Built Python and FastAPI services.",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["rag"]["used"] is False
    assert data["rag"]["chunks"] == []
    # Base CV has no Kubernetes, so the fake tailor won't claim it — unchanged flow.
    assert all("Kubernetes" not in b for b in data["tailor"]["bullets"])
