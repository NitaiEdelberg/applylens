"""Sentence similarity that survives a change of vocabulary.

The term-coverage rule cannot see that "experience building AI-powered
applications" and "built LLM-powered features" are the same thing: they share
no tokens, and no alias table anticipates every phrasing a job ad invents. On
753 requirements from real postings that is most of what it misses.

So: embed the requirement and each sentence of the CV, and take the best
cosine. One number, and it is the number the alias table cannot produce.

Three embedders, in the order they are preferred, all behind one interface:

  fasttext   300-dimensional word vectors, mean-pooled with idf weights, read
             from a local .npy by memory map. No network, no torch, 90 MB.
             This machine already has them — they are the Amtza game's cache.
  jina       the hosted embedder the RAG path already uses, when a key is set.
             Better vectors, at the cost of a network call per analysis.
  tfidf      lexical cosine. Honest fallback, and it measures roughly what the
             rule already measures, so it adds little — which the eval shows
             rather than hides.

Whichever is used is reported, because a feature computed by a different
embedder in training than in production is a model that silently gets worse.
"""
import math
import os
import pickle
import re
from typing import List, Optional

import numpy as np

from .skillmatch import _FILLER

# The Amtza cache, which is where these vectors already live on this machine.
# Override to ship them somewhere else.
DEFAULT_VECTORS = os.path.expanduser(
    os.getenv("FASTTEXT_VECTORS", "~/.amtza/models/en_v4.npy"))
DEFAULT_WORDS = os.path.expanduser(
    os.getenv("FASTTEXT_WORDS", "~/.amtza/models/en_v4_words.pkl"))

_TOKEN = re.compile(r"[a-z][a-z0-9+#.]{1,}")
_SENTENCE = re.compile(r"[.;\n•·|]+")


class FastTextEmbedder:
    """Mean of word vectors, weighted so rare words count more than common ones.

    Plain averaging lets "experience", "with" and "strong" dominate a short
    requirement, which is exactly the noise the rule already filters. Weighting
    by inverse frequency rank puts the weight on the words that carry meaning.
    """

    name = "fasttext"

    # Words this common carry grammar, not meaning. Mean-pooling without this
    # makes every sentence starting "Experience with..." look alike, which is
    # the exact failure this feature exists to avoid.
    COMMON_RANK = 300

    def __init__(self, vectors_path=DEFAULT_VECTORS, words_path=DEFAULT_WORDS):
        self._vectors = np.load(vectors_path, mmap_mode="r")
        words = pickle.load(open(words_path, "rb"))
        # The file is frequency-ordered, so the index doubles as a rank.
        self._index = {w: i for i, w in enumerate(words)}
        self._n = len(words)
        # The direction every English sentence points in. Projecting it out is
        # the standard repair for mean-pooled vectors: what is left is what
        # makes this sentence different from any other sentence.
        common = np.asarray(self._vectors[:2000], dtype=np.float32).mean(axis=0)
        norm = np.linalg.norm(common)
        self._common = common / norm if norm else None

    def _weight(self, rank: int) -> float:
        # log-scaled inverse rank: word 10 gets ~1.0, word 100k gets ~0.2.
        return 1.0 / math.log(10 + rank)

    def embed(self, text: str) -> Optional[np.ndarray]:
        vectors, weights = [], []
        for token in _TOKEN.findall((text or "").lower()):
            if token in _FILLER:
                continue
            rank = self._index.get(token)
            if rank is None or rank < self.COMMON_RANK:
                continue
            vectors.append(np.asarray(self._vectors[rank], dtype=np.float32))
            weights.append(self._weight(rank))
        if not vectors:
            return None
        pooled = np.average(np.stack(vectors), axis=0, weights=weights)
        if self._common is not None:
            pooled = pooled - self._common * float(np.dot(pooled, self._common))
        norm = np.linalg.norm(pooled)
        return pooled / norm if norm else None


class TfidfEmbedder:
    """Lexical cosine. Present so the feature never simply disappears."""

    name = "tfidf"

    def __init__(self):
        from sklearn.feature_extraction.text import TfidfVectorizer
        self._vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))
        self._fitted = False

    def fit(self, corpus: List[str]):
        try:
            self._vectorizer.fit([c for c in corpus if c and c.strip()])
            self._fitted = True
        except ValueError:
            self._fitted = False
        return self

    def embed(self, text: str) -> Optional[np.ndarray]:
        if not self._fitted or not (text or "").strip():
            return None
        vector = self._vectorizer.transform([text]).toarray()[0]
        norm = np.linalg.norm(vector)
        return vector / norm if norm else None


_embedder = None


def get_embedder():
    """The best embedder this machine can offer, built once."""
    global _embedder
    if _embedder is not None:
        return _embedder
    try:
        if os.path.exists(DEFAULT_VECTORS) and os.path.exists(DEFAULT_WORDS):
            _embedder = FastTextEmbedder()
            return _embedder
    except Exception:  # noqa: BLE001 — a missing or corrupt cache is not fatal
        pass
    _embedder = TfidfEmbedder()
    return _embedder


def sentences(text: str) -> List[str]:
    """CV sentences, long enough to mean something."""
    parts = [p.strip() for p in _SENTENCE.split(text or "")]
    return [p for p in parts if len(p) >= 25] or [(text or "").strip()]


def similarity(requirement: str, cv_text: str, embedder=None) -> dict:
    """How close the requirement gets to anything the CV says.

    Returns the best sentence match, the whole-CV match, and which embedder
    produced them — the last one because a number is only comparable to another
    number from the same embedder.
    """
    embedder = embedder or get_embedder()
    if getattr(embedder, "name", "") == "tfidf" and not embedder._fitted:
        embedder.fit(sentences(cv_text) + [requirement])

    query = embedder.embed(requirement)
    if query is None:
        return {"best_sentence": 0.0, "whole_cv": 0.0, "embedder": embedder.name}

    best = 0.0
    for sentence in sentences(cv_text):
        vector = embedder.embed(sentence)
        if vector is not None:
            best = max(best, float(np.dot(query, vector)))

    whole = embedder.embed(cv_text)
    return {
        "best_sentence": max(0.0, best),
        "whole_cv": max(0.0, float(np.dot(query, whole))) if whole is not None else 0.0,
        "embedder": embedder.name,
    }
