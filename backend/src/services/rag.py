"""RAG over an optional career-history corpus (Circle 4).

For each job we retrieve the most relevant pieces of a longer career history
(more than fits in one CV) so tailoring can draw on the user's FULL background
while staying grounded — the retrieved chunks join the CV as the source of truth
the grounding guardrail verifies against.

Built on langchain-core's `Embeddings` interface + `InMemoryVectorStore`, with a
pluggable embedder so the whole feature is testable locally with NO API key:

  - ``GeminiEmbeddings`` — hosted Gemini embeddings REST API (``text-embedding-004``),
    used when ``GEMINI_API_KEY`` is set.
  - ``TfidfEmbeddings`` — a local scikit-learn TF-IDF fallback fit on the corpus
    chunks; deterministic, no network. Used when no key is present.

Both implement ``embed_documents`` / ``embed_query``. Retrieval uses cosine
similarity (InMemoryVectorStore's default), which matches TF-IDF geometry.
"""
from __future__ import annotations

import logging
import re
from typing import List, Union

import httpx
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import InMemoryVectorStore
from sklearn.feature_extraction.text import TfidfVectorizer

from ..config import (
    GEMINI_API_KEY,
    GEMINI_EMBED_MODEL,
    JINA_API_KEY,
    JINA_EMBED_MODEL,
)

logger = logging.getLogger(__name__)

# Drop tiny paragraphs (section headers, stray one-word lines) so noise chunks
# never crowd out real experiences in the top-k.
_MIN_CHUNK_CHARS = 40


def default_source() -> str:
    """Which embedder would be used right now, in preference order."""
    if JINA_API_KEY:
        return "jina"
    if GEMINI_API_KEY:
        return "gemini"
    return "tfidf"


# ---- pluggable embedders (LangChain Embeddings interface) ----
class JinaEmbeddings(Embeddings):
    """LangChain ``Embeddings`` backed by Jina's free embeddings API.

    Free, no credit card, no region restriction, and it embeds a whole batch of
    texts in ONE request. Network/HTTP errors propagate so the caller can fall
    back to the local TF-IDF embedder.
    """

    def __init__(self, api_key: str, model: str = JINA_EMBED_MODEL, timeout: float = 30.0):
        if not api_key:
            raise ValueError("JinaEmbeddings requires an API key")
        self._api_key = api_key
        self._model = model
        self._url = "https://api.jina.ai/v1/embeddings"
        self._timeout = timeout

    def _embed(self, texts: List[str]) -> List[List[float]]:
        resp = httpx.post(
            self._url,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={"model": self._model, "input": texts},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = sorted(resp.json()["data"], key=lambda d: d.get("index", 0))
        return [[float(v) for v in d["embedding"]] for d in data]

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self._embed(texts)

    def embed_query(self, text: str) -> List[float]:
        return self._embed([text])[0]



class GeminiEmbeddings(Embeddings):
    """LangChain ``Embeddings`` backed by Gemini's ``embedContent`` REST API.

    One request per text via httpx. Network/HTTP errors propagate so the caller
    can fall back to the local TF-IDF embedder.
    """

    def __init__(self, api_key: str, model: str = GEMINI_EMBED_MODEL, timeout: float = 30.0):
        if not api_key:
            raise ValueError("GeminiEmbeddings requires an API key")
        self._api_key = api_key
        self._url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:embedContent"
        )
        self._timeout = timeout

    def _embed_one(self, text: str) -> List[float]:
        resp = httpx.post(
            self._url,
            params={"key": self._api_key},
            json={"content": {"parts": [{"text": text}]}},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        values = resp.json()["embedding"]["values"]
        return [float(v) for v in values]

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [self._embed_one(t) for t in texts]

    def embed_query(self, text: str) -> List[float]:
        return self._embed_one(text)


class TfidfEmbeddings(Embeddings):
    """Deterministic local TF-IDF embedder (scikit-learn) — no key, no network.

    Must be ``fit`` on the corpus chunks before use so that ``embed_query``
    projects a query into the SAME vocabulary space as the stored documents.
    """

    def __init__(self):
        self._vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))
        self._fitted = False
        self._dim = 0

    def fit(self, corpus: List[str]) -> "TfidfEmbeddings":
        # Guard an all-stop-word / empty corpus so a ValueError doesn't escape.
        try:
            self._vectorizer.fit(corpus)
            self._dim = len(self._vectorizer.get_feature_names_out())
            self._fitted = True
        except ValueError:
            self._fitted = False
            self._dim = 1
        return self

    def _vectorize(self, texts: List[str]) -> List[List[float]]:
        return self._vectorizer.transform(texts).toarray().tolist()

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        if not self._fitted:
            self.fit(texts)
        if not self._fitted:  # still un-fittable (empty vocab) → zero vectors
            return [[0.0] * self._dim for _ in texts]
        return self._vectorize(texts)

    def embed_query(self, text: str) -> List[float]:
        # An unfitted embedder or an all-OOV query yields a zero vector; the
        # store's cosine similarity treats that as 0 (no crash), not an error.
        if not self._fitted:
            return [0.0] * self._dim
        return self._vectorize([text])[0]


# ---- chunking + query normalization ----
def _chunk(career_text: str) -> List[str]:
    """Split a career history into paragraph chunks, dropping tiny fragments."""
    if not career_text or not career_text.strip():
        return []
    parts = re.split(r"\n\s*\n", career_text.strip())
    chunks = [p.strip() for p in parts if len(p.strip()) >= _MIN_CHUNK_CHARS]
    if not chunks:
        # No blank-line structure (one blob) — keep the whole thing if it's real.
        whole = career_text.strip()
        if len(whole) >= _MIN_CHUNK_CHARS:
            chunks = [whole]
    return chunks


def _as_query(job_requirements: Union[List[str], str]) -> str:
    if isinstance(job_requirements, (list, tuple)):
        return "\n".join(str(r).strip() for r in job_requirements if str(r).strip())
    return str(job_requirements or "").strip()


def _retrieve(chunks: List[str], embedder: Embeddings, query: str, k: int) -> List[str]:
    store = InMemoryVectorStore(embedder)
    store.add_texts(chunks)
    retriever = store.as_retriever(search_kwargs={"k": k})
    docs = retriever.invoke(query)
    return [d.page_content for d in docs]


# ---- public API ----
def retrieve_context(
    job_requirements: Union[List[str], str],
    career_text: str,
    k: int = 4,
) -> dict:
    """Retrieve the top-k career-history chunks most relevant to a job.

    Chunks ``career_text`` by paragraph, embeds them (Gemini when a key is set,
    else local TF-IDF), builds an in-memory vector store, and returns the k most
    similar chunks to ``job_requirements`` (a list of requirement strings or raw
    JD text). Empty career history → ``{"chunks": [], "source": ...}``.

    Returns ``{"chunks": [str], "source": "gemini" | "tfidf"}``. If the Gemini
    embedder fails (network / invalid key), it falls back to TF-IDF so the
    feature keeps working and ``source`` reflects what was actually used.
    """
    query = _as_query(job_requirements)
    chunks = _chunk(career_text)
    if not chunks or not query:
        return {"chunks": [], "source": default_source()}

    # Preference order: Jina (free hosted) -> Gemini (if billed) -> local TF-IDF.
    if JINA_API_KEY:
        try:
            retrieved = _retrieve(chunks, JinaEmbeddings(JINA_API_KEY), query, k)
            return {"chunks": retrieved, "source": "jina"}
        except Exception as exc:  # noqa: BLE001 — degrade to the next embedder
            logger.warning("Jina embeddings failed (%s); falling back", exc)

    if GEMINI_API_KEY:
        try:
            retrieved = _retrieve(chunks, GeminiEmbeddings(GEMINI_API_KEY), query, k)
            return {"chunks": retrieved, "source": "gemini"}
        except Exception as exc:  # noqa: BLE001 — degrade to the local embedder
            logger.warning("Gemini embeddings failed (%s); falling back to TF-IDF", exc)

    retrieved = _retrieve(chunks, TfidfEmbeddings().fit(chunks), query, k)
    return {"chunks": retrieved, "source": "tfidf"}
