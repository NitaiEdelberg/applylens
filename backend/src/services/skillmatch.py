"""Deterministic, CPU-only skill-coverage signal — a non-LLM second opinion.

For each extracted job requirement, checks how many of its meaningful terms
actually appear in the CV, using scikit-learn's text analyzer (lowercasing,
tokenization, English stop-word removal). A requirement is "covered" when at
least `threshold` of its terms are present in the CV. Deterministic, no LLM, no
network, no torch — a keyword-coverage heuristic that complements (never
replaces) the LLM's semantic fit score.

Why term overlap and not TF-IDF cosine against the whole CV: cosine between a
short requirement and a long CV is diluted by the CV's many other terms, so
genuine matches (e.g. a one-word "JavaScript", or "BSc in Computer Science")
score below any useful threshold and get wrongly flagged as missing. Checking
term presence answers "does the CV actually mention this?" directly, accurately,
and interpretably.
"""
from sklearn.feature_extraction.text import TfidfVectorizer

_METHOD = "keyword term coverage"

# One analyzer, reused: lowercases, tokenizes (word chars, len >= 2, so "BSc/MSc"
# -> "bsc","msc" and "Node.js" -> "node","js"), and strips English stop words.
_ANALYZE = TfidfVectorizer(stop_words="english").build_analyzer()


def skill_match(requirements: list, cv_text: str, threshold: float = 0.5) -> dict:
    """Deterministic keyword-term coverage of `requirements` by `cv_text`.

    Returns:
        {
          "coverage_score": int,      # 0-100 = covered / total * 100
          "covered": [{"requirement": str, "score": float}],  # sorted high→low
          "missing": [str],
          "method": "keyword term coverage",
        }

    Empty requirements or an empty CV degrade to a 0 score — never raises.
    """
    reqs = [r.strip() for r in (requirements or []) if r and r.strip()]
    cv = (cv_text or "").strip()

    if not reqs or not cv:
        return {
            "coverage_score": 0,
            "covered": [],
            "missing": list(reqs),  # nothing can be covered with an empty CV
            "method": _METHOD,
        }

    cv_tokens = set(_ANALYZE(cv))

    covered = []
    missing = []
    for req in reqs:
        terms = set(_ANALYZE(req))
        if terms:
            present = sum(1 for t in terms if t in cv_tokens)
            frac = present / len(terms)
            is_covered = frac >= threshold
        else:
            # Requirement had no analyzable terms (all stop words, or symbol-only
            # like "C++") — fall back to a case-insensitive substring check.
            is_covered = req.lower() in cv.lower()
            frac = 1.0 if is_covered else 0.0

        if is_covered:
            covered.append({"requirement": req, "score": round(frac, 2)})
        else:
            missing.append(req)

    covered.sort(key=lambda c: c["score"], reverse=True)
    coverage_score = int(len(covered) / len(reqs) * 100)

    return {
        "coverage_score": coverage_score,
        "covered": covered,
        "missing": missing,
        "method": _METHOD,
    }
