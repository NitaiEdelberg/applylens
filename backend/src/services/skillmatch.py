"""Deterministic, CPU-only skill-coverage signal — a non-LLM second opinion.

For each extracted job requirement, this answers "does the CV actually mention
this?" without asking a model, so the UI can show a signal that disagrees with
the LLM's fit score on purpose. No LLM, no network, no torch.

The first version compared raw tokens, which made it dishonest in the other
direction: a CV saying "wrote SQL against Snowflake and BigQuery" was scored as
MISSING "SQL against a cloud warehouse" (snowflake is not the token warehouse),
and "worked directly with customers" was scored as missing "customer-facing
experience" (customers is not the token customer). Measured on the labelled
cases in evals/skillmatch_cases.jsonl, that baseline recalls barely half of the
requirements a person would call covered.

Three things fix that, in ascending order of how much explaining they need:

1. Filler terms in a requirement ("strong", "3+ years", "experience with") are
   dropped, so scoring is over the words that carry the requirement.
2. Every token is expanded to a small set of surface forms (plural, gerund,
   past tense), and matching is set intersection, so customers == customer.
3. A named tool is evidence for the category it belongs to: snowflake implies
   warehouse and sql, fastapi implies python and api. This is directional on
   purpose — naming Snowflake proves you touched a warehouse, but the word
   "warehouse" does not prove you have used Snowflake.

Every decision is reported with the evidence term that caused it, so the panel
can show WHY a requirement counted as covered instead of asking for trust.
"""
import difflib
import re

from sklearn.feature_extraction.text import TfidfVectorizer

_METHOD = "term coverage with morphology + tool-to-category evidence"

# One analyzer, reused: lowercases, tokenizes (word chars, len >= 2, so "BSc/MSc"
# -> "bsc","msc" and "Node.js" -> "node","js"), and strips English stop words.
_ANALYZE = TfidfVectorizer(stop_words="english").build_analyzer()

# Words that appear in requirements but carry no requirement: scoring "strong
# Python" over {strong, python} halves the score of a CV that says Python.
_FILLER = {
    "ability", "able", "background", "build", "building", "builds",
    "comfortable", "demonstrated", "deep", "develop", "developing",
    "excellent", "experience", "experiences", "familiar", "familiarity", "good",
    "great", "hands", "high", "knowledge", "level", "min", "minimum", "nice",
    "plus", "preferred", "proficiency", "proficient", "proven", "record",
    "required", "skill", "skills", "solid", "strong", "track", "understanding",
    "using", "work", "working", "year", "years",
}

# A named tool is evidence for the category it belongs to. Directional: the key
# (what the CV says) implies the values (what the job asked for), never back.
_IMPLIES = {
    "snowflake": {"warehouse", "warehousing", "cloud", "sql", "data", "analytics"},
    "bigquery": {"warehouse", "warehousing", "cloud", "sql", "data", "analytics", "gcp"},
    "redshift": {"warehouse", "warehousing", "cloud", "sql", "data", "aws"},
    "databricks": {"warehouse", "warehousing", "cloud", "sql", "data", "spark"},
    "postgres": {"sql", "database", "rdbms", "relational"},
    "postgresql": {"sql", "database", "rdbms", "relational"},
    "mysql": {"sql", "database", "rdbms", "relational"},
    "sqlite": {"sql", "database", "rdbms", "relational"},
    "mongodb": {"database", "nosql"},
    "mongo": {"database", "nosql"},
    "fastapi": {"python", "api", "apis", "rest", "backend", "web"},
    "flask": {"python", "api", "apis", "rest", "backend", "web"},
    "django": {"python", "api", "apis", "rest", "backend", "web"},
    "pandas": {"python", "data", "analytics"},
    "numpy": {"python", "data"},
    "sklearn": {"python", "ml", "machine", "learning"},
    "scikit": {"python", "ml", "machine", "learning"},
    "pytorch": {"python", "ml", "machine", "learning", "deep"},
    "tensorflow": {"python", "ml", "machine", "learning", "deep"},
    "react": {"frontend", "javascript", "ui", "web"},
    "vue": {"frontend", "javascript", "ui", "web"},
    "angular": {"frontend", "typescript", "javascript", "ui", "web"},
    "node": {"javascript", "backend", "api", "apis", "server"},
    "nodejs": {"javascript", "backend", "api", "apis", "server"},
    "express": {"javascript", "backend", "api", "apis", "rest", "server"},
    "typescript": {"javascript"},
    "groq": {"llm", "llms", "ai", "genai", "model", "models"},
    "openai": {"llm", "llms", "ai", "genai", "model", "models"},
    "anthropic": {"llm", "llms", "ai", "genai", "model", "models"},
    "claude": {"llm", "llms", "ai", "genai", "model", "models"},
    "gemini": {"llm", "llms", "ai", "genai", "model", "models"},
    "gpt": {"llm", "llms", "ai", "genai", "model", "models"},
    "llama": {"llm", "llms", "ai", "genai", "model", "models"},
    "langchain": {"llm", "llms", "ai", "genai", "rag", "orchestration"},
    "rag": {"llm", "llms", "retrieval", "embeddings", "ai"},
    "embeddings": {"ml", "retrieval", "vector", "nlp"},
    "fasttext": {"embeddings", "nlp", "ml", "vector"},
    "prompt": {"llm", "llms", "ai", "genai"},
    "k8s": {"kubernetes", "containers", "orchestration"},
    "kubernetes": {"containers", "orchestration", "devops"},
    "docker": {"containers", "devops"},
    "terraform": {"iac", "infrastructure", "devops"},
    "aws": {"cloud", "devops"},
    "gcp": {"cloud", "devops"},
    "azure": {"cloud", "devops"},
    "customer": {"client", "clients", "customers", "facing", "stakeholder", "stakeholders"},
    "customers": {"client", "clients", "customer", "facing", "stakeholder", "stakeholders"},
    "client": {"customer", "customers", "clients", "facing", "stakeholder", "stakeholders"},
    "clients": {"customer", "customers", "client", "facing", "stakeholder", "stakeholders"},
    "socket": {"realtime", "websockets"},
    "websocket": {"realtime", "sockets"},
    "git": {"version", "control"},
    "pytest": {"testing", "tests", "test", "python"},
    "vitest": {"testing", "tests", "test", "javascript"},
    "jest": {"testing", "tests", "test", "javascript"},
}

# Requirements a CV cannot evidence, however carefully it is read. A person
# labelling these said "not covered" on every one; the LLM annotator said
# "covered" on nearly all of them, because a CV that mentions customers or a
# team superficially resembles "strong communication". Both answers are wrong:
# the honest verdict is that this signal has nothing to say, and claiming a
# match here is the most confident-sounding way for it to lie.
#
# They are reported separately rather than dropped, because a job asking for
# five of these is telling the candidate something, and a coverage score that
# silently ignored half a posting would be its own kind of dishonest.
_UNASSESSABLE = re.compile(
    r"\b(communication|communicat\w+|interpersonal|team\s*player|collaborat\w+|"
    r"attention to detail|detail[- ]oriented|self[- ]starter|proactive|"
    r"problem[- ]solving|analytical thinking|critical thinking|"
    r"stakeholder management|work ethic|fast[- ]paced|adaptab\w+|"
    r"passionate|motivated|independent\w*|ownership|can[- ]do|"
    r"written and (?:oral|verbal)|verbal and written|"
    r"ability to (?:translate|define|articulate|influence|prioriti[sz]e)|"
    r"high accuracy|willingness to learn|growth mindset|curious)\b",
    re.IGNORECASE)

# The other thing a CV cannot settle: how long someone has been doing it. The
# LLM fit score judges seniority; term coverage cannot.
_TENURE = re.compile(r"\b\d+\s*\+?\s*(?:years?|yrs?)\b", re.IGNORECASE)


def assessable(requirement: str) -> bool:
    """False for requirements about traits or tenure rather than skills."""
    text = requirement or ""
    return not (_UNASSESSABLE.search(text) or _TENURE.search(text))


# How close two tokens must look before one counts as the other (postgres /
# postgresql). Deliberately tight: at 0.85 "react" starts matching "retail".
_FUZZY = 0.92

# Shortest token that may match by prefix. Below this, "go" would cover "gcp".
_MIN_PREFIX = 4
# ...and how much of a tail may differ. "java" vs "javascript" is 6, and they
# are different languages; "node" vs "nodejs" is 2, and they are the same one.
_MAX_PREFIX_TAIL = 2

# A requirement is often several requirements. Commas and "and" join things that
# must ALL be present; "or" and "/" offer alternatives where ANY will do.
_CONJUNCTION = re.compile(r",|\band\b|;", re.IGNORECASE)
_ALTERNATIVE = re.compile(r"/|\bor\b", re.IGNORECASE)


def _parts(requirement: str):
    """Requirement -> [[alternative, ...], ...]; every group must be covered."""
    groups = []
    for conjunct in _CONJUNCTION.split(requirement):
        alts = [a.strip() for a in _ALTERNATIVE.split(conjunct) if a.strip()]
        if alts:
            groups.append(alts)
    return groups or [[requirement]]


def _forms(token: str) -> set:
    """Surface variants of a token, so customers and customer meet in the middle.

    Returns a SET rather than one canonical stem: a crude stemmer turns facing
    into fac, which no real word matches, but keeping facing, fac and face in
    the set means the right one is there whichever side it came from.
    """
    out = {token}
    if len(token) > 4 and token.endswith("ies"):
        out.add(token[:-3] + "y")
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        out.add(token[:-1])
    if len(token) > 4 and token.endswith("es"):
        out.add(token[:-2])
    if len(token) > 5 and token.endswith("ing"):
        out.add(token[:-3])
        out.add(token[:-3] + "e")
    if len(token) > 4 and token.endswith("ed"):
        out.add(token[:-2])
        out.add(token[:-1])
    return out


def _cv_index(cv_text: str):
    """Everything the CV can be evidence for: form -> (CV token, how it matched).

    The "how" is kept because it is the interesting part: a requirement covered
    because the CV literally says the word is a different kind of match from one
    covered because the CV names a tool in that category. The UI shows it, and
    the learned model in evals/train_coverage_model.py uses it as a feature.
    """
    evidence = {}
    for token in _ANALYZE(cv_text):
        evidence.setdefault(token, (token, "exact"))
        for form in _forms(token):
            evidence.setdefault(form, (token, "morphology"))
        for implied in _IMPLIES.get(token, ()):
            evidence.setdefault(implied, (token, "category"))
    return evidence


def _match_term(term: str, evidence: dict):
    """The CV token that covers `term`, or None.

    Exact forms first, then a prefix rule (node/nodejs, postgres/postgresql —
    difflib scores those at 0.80 and 0.89, below any cutoff that is still safe
    for short tokens), then fuzzy as a last resort.
    """
    if term in evidence:
        return evidence[term]
    for form in _forms(term):
        if form in evidence:
            token, how = evidence[form]
            return (token, "morphology" if how == "exact" else how)
    if len(term) >= _MIN_PREFIX:
        for known in evidence:
            if len(known) < _MIN_PREFIX:
                continue
            short, long = sorted((term, known), key=len)
            # Only a short tail may differ (postgres/postgresql, node/nodejs).
            # Without that bound, java matches javascript.
            if long.startswith(short) and len(long) - len(short) <= _MAX_PREFIX_TAIL:
                return (evidence[known][0], "prefix")
    close = difflib.get_close_matches(term, list(evidence), n=1, cutoff=_FUZZY)
    return (evidence[close[0]][0], "fuzzy") if close else None


def _mentions(needle: str, haystack: str) -> bool:
    """Whole-token substring search, for requirements with no analyzable terms.

    Bounded on both sides because a plain `in` check reports the requirement
    "Go" as covered by a CV that only says MongoDB.
    """
    return re.search(
        r"(?<![A-Za-z0-9])" + re.escape(needle.lower()) + r"(?![A-Za-z0-9])",
        haystack.lower(),
    ) is not None


def _score_one(text: str, cv: str, evidence: dict):
    """Fraction of `text`'s carrying terms the CV evidences, plus the reasons."""
    terms = [t for t in dict.fromkeys(_ANALYZE(text)) if t not in _FILLER]
    if not terms:
        # All filler, or symbol-only like "C++": fall back to a bounded search.
        return (1.0, [{"term": text, "evidence": text}], []) if _mentions(text, cv) \
            else (0.0, [], [text])

    matched, unmatched = [], []
    for term in terms:
        hit = _match_term(term, evidence)
        if hit:
            matched.append({"term": term, "evidence": hit[0], "how": hit[1]})
        else:
            unmatched.append(term)
    return len(matched) / len(terms), matched, unmatched


def skill_match(requirements: list, cv_text: str, threshold: float = 0.5) -> dict:
    """Deterministic coverage of `requirements` by `cv_text`.

    Returns:
        {
          "coverage_score": int,      # 0-100 = covered / total * 100
          "covered": [{"requirement": str, "score": float,
                       "matched": [{"term": str, "evidence": str, "how": str}]}],
          "missing": [str],                                    # requirement text
          "missing_detail": [{"requirement": str, "unmatched": [str]}],
          "method": str,
        }

    Empty requirements or an empty CV degrade to a 0 score — never raises.
    """
    reqs = [r.strip() for r in (requirements or []) if r and r.strip()]
    cv = (cv_text or "").strip()

    if not reqs or not cv:
        return {
            "coverage_score": 0,
            "covered": [],
            "missing": list(reqs),
            "missing_detail": [{"requirement": r, "unmatched": []} for r in reqs],
            "not_assessed": [],
            "method": _METHOD,
        }

    evidence = _cv_index(cv)

    covered, missing, not_assessed = [], [], []
    for req in reqs:
        if not assessable(req):
            not_assessed.append(req)
            continue
        # "SQL, Python and Kubernetes" is three requirements wearing one coat:
        # scoring it as a bag of terms called it covered at 2 of 3. Every
        # conjunct has to stand on its own; alternatives inside one only need
        # a single hit.
        scores, matched, unmatched = [], [], []
        for alternatives in _parts(req):
            best = None
            for alt in alternatives:
                frac, hits, misses = _score_one(alt, cv, evidence)
                if best is None or frac > best[0]:
                    best = (frac, hits, misses)
            scores.append(best[0])
            matched.extend(best[1])
            unmatched.extend(best[2])

        frac = sum(scores) / len(scores)
        # Every conjunct must clear the bar, not just the average.
        if all(sc >= threshold for sc in scores):
            covered.append({"requirement": req, "score": round(frac, 2), "matched": matched})
        else:
            missing.append({"requirement": req, "unmatched": unmatched})

    covered.sort(key=lambda c: c["score"], reverse=True)
    judged = len(covered) + len(missing)
    return {
        "coverage_score": int(len(covered) / judged * 100) if judged else 0,
        "covered": covered,
        # `missing` stays a plain list of requirement strings because that is
        # what the UI renders; the per-term reasons ride alongside it.
        "missing": [m["requirement"] for m in missing],
        "missing_detail": missing,
        # Requirements this signal deliberately declines to judge: traits a CV
        # cannot evidence, and years it cannot count. Excluded from the score.
        "not_assessed": not_assessed,
        "method": _METHOD,
    }
