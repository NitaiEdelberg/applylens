"""Deterministic, CPU-only skill-coverage signal — a non-LLM second opinion.

Uses classic TF-IDF vectorization + cosine similarity (scikit-learn) to measure
how well a CV covers a job's extracted requirements. No LLM call, no network,
no torch/transformers — same inputs always produce the same output. It is a
keyword/TF-IDF coverage heuristic that *complements* (never replaces) the LLM's
semantic fit score.
"""
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def skill_match(requirements: list, cv_text: str, threshold: float = 0.12) -> dict:
    """Compute deterministic TF-IDF keyword coverage of `requirements` by `cv_text`.

    Fits a TF-IDF vectorizer (english stop words, unigrams+bigrams) over the CV
    plus each requirement, then scores every requirement by cosine similarity to
    the CV vector. A requirement is "covered" when its similarity >= threshold.

    Returns a dict:
        {
          "coverage_score": int,      # 0-100 = covered / total * 100
          "covered": [{"requirement": str, "score": float}],  # sorted high→low
          "missing": [str],
          "method": "tf-idf cosine",
        }

    Empty requirements or an empty CV degrade gracefully to a 0 score and empty
    lists — never raises.
    """
    # Normalize: keep only non-empty requirement strings.
    reqs = [r.strip() for r in (requirements or []) if r and r.strip()]
    cv = (cv_text or "").strip()

    if not reqs or not cv:
        return {
            "coverage_score": 0,
            "covered": [],
            "missing": list(reqs),  # nothing can be covered with an empty CV
            "method": "tf-idf cosine",
        }

    # Fit over [cv] + requirements so the vocabulary spans both sides. Row 0 is
    # the CV; rows 1..N are the requirements.
    corpus = [cv] + reqs
    try:
        vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))
        matrix = vectorizer.fit_transform(corpus)
    except ValueError:
        # Empty vocabulary (e.g. every token is a stop word) — nothing to match.
        return {
            "coverage_score": 0,
            "covered": [],
            "missing": reqs,
            "method": "tf-idf cosine",
        }

    cv_vec = matrix[0:1]
    req_vecs = matrix[1:]
    sims = cosine_similarity(req_vecs, cv_vec).ravel()

    covered = []
    missing = []
    for req, sim in zip(reqs, sims):
        score = round(float(sim), 2)
        if sim >= threshold:
            covered.append({"requirement": req, "score": score})
        else:
            missing.append(req)

    covered.sort(key=lambda c: c["score"], reverse=True)
    coverage_score = int(len(covered) / len(reqs) * 100)

    return {
        "coverage_score": coverage_score,
        "covered": covered,
        "missing": missing,
        "method": "tf-idf cosine",
    }
