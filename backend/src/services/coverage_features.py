"""Features for the learned coverage model.

Every number here is one the rule already computes and a person can read out
loud. That is the point of the feature choice: a logistic regression over these
produces coefficients you can put on a slide — "a category match is worth twice
what a fuzzy match is worth" — where the same model over TF-IDF n-grams
produces four hundred numbers nobody can defend.

Lives in the service package rather than in evals/ because if the model wins,
production imports this exact function. A feature computed one way in training
and another way at inference is the classic way a model that scored 0.94
offline scores 0.7 in production.
"""
from typing import Dict, List

from .skillmatch import (
    _ANALYZE, _FILLER, _cv_index, _match_term, _mentions, _parts, skill_match,
)

# Order matters: the training script reports coefficients against these names.
FEATURE_NAMES = [
    "term_coverage",       # share of carrying terms the CV evidences
    "n_terms",             # how many carrying terms the requirement has
    "exact_share",         # of matched terms, share matched literally
    "morphology_share",    # ...matched through a plural/tense variant
    "category_share",      # ...matched because a named tool implies the category
    "prefix_share",        # ...matched as node/nodejs
    "fuzzy_share",         # ...matched by string similarity (the weakest evidence)
    "worst_conjunct",      # the lowest-scoring part of a multi-part requirement
    "n_conjuncts",         # "SQL, Python and Kubernetes" is three requirements
    "has_alternatives",    # "search / embeddings" only needs one hit
    "requirement_chars",
    "cv_tokens",
    "rule_says_covered",   # what the shipped rule decided, so the model can
                           # learn when to overrule it rather than relearn it
]


def _score_alternative(text: str, cv_text: str, evidence) -> Dict[str, float]:
    terms = [t for t in dict.fromkeys(_ANALYZE(text)) if t not in _FILLER]
    if not terms:
        hit = _mentions(text, cv_text)
        return {"coverage": 1.0 if hit else 0.0, "n_terms": 0,
                "hows": ["exact"] if hit else []}
    hows = []
    for term in terms:
        found = _match_term(term, evidence)
        if found:
            hows.append(found[1])
    return {"coverage": len(hows) / len(terms), "n_terms": len(terms), "hows": hows}


def features(requirement: str, cv_text: str) -> List[float]:
    """One row of features for a (requirement, CV) pair, in FEATURE_NAMES order."""
    evidence = _cv_index(cv_text or "")
    groups = _parts(requirement or "")

    per_conjunct, hows, total_terms = [], [], 0
    has_alternatives = 0
    for alternatives in groups:
        if len(alternatives) > 1:
            has_alternatives = 1
        best = max((_score_alternative(alt, cv_text, evidence) for alt in alternatives),
                   key=lambda s: s["coverage"])
        per_conjunct.append(best["coverage"])
        hows.extend(best["hows"])
        total_terms += best["n_terms"]

    matched = len(hows) or 1  # shares are of matched terms; avoid dividing by zero
    def share(kind):
        return sum(1 for h in hows if h == kind) / matched if hows else 0.0

    return [
        sum(per_conjunct) / len(per_conjunct) if per_conjunct else 0.0,
        float(total_terms),
        share("exact"),
        share("morphology"),
        share("category"),
        share("prefix"),
        share("fuzzy"),
        min(per_conjunct) if per_conjunct else 0.0,
        float(len(groups)),
        float(has_alternatives),
        float(len(requirement or "")),
        float(len(_ANALYZE(cv_text or ""))),
        1.0 if skill_match([requirement], cv_text)["covered"] else 0.0,
    ]
