"""Behaviour of the deterministic coverage signal.

The numbers this signal shows sit next to the LLM's fit score as an independent
second opinion, so a wrong "missing" is not cosmetic: it tells someone their CV
lacks a skill it plainly states. These cases pin the rules that earn that trust.
The aggregate precision/recall live in evals/run_skillmatch_eval.py.
"""
from src.services.skillmatch import skill_match

CV = (
    "AI Solutions Engineer: built LLM-powered features, wrote SQL against Snowflake "
    "and BigQuery, worked directly with customers. Python, FastAPI, React, Node.js, "
    "MongoDB, PostgreSQL."
)


def covered(reqs, cv=CV):
    return {c["requirement"] for c in skill_match(reqs, cv)["covered"]}


def test_plural_and_tense_are_the_same_word():
    assert covered(["Customer-facing experience"]) == {"Customer-facing experience"}
    assert covered(["Building LLM-powered features"]) == {"Building LLM-powered features"}


def test_a_named_tool_is_evidence_for_its_category():
    result = skill_match(["SQL against a cloud warehouse"], CV)
    assert result["covered"], "Snowflake and BigQuery are cloud warehouses"
    evidence = {m["evidence"] for m in result["covered"][0]["matched"]}
    assert "snowflake" in evidence or "bigquery" in evidence


def test_the_category_is_not_evidence_for_a_named_tool():
    # Naming a warehouse proves you used one; saying "warehouse" does not prove
    # you used Snowflake. The implication only runs one way.
    assert not skill_match(["Snowflake"], "Built a cloud data warehouse")["covered"]


def test_filler_words_do_not_dilute_a_real_match():
    assert covered(["Proven track record of strong hands-on Python development"])


def test_every_conjunct_must_stand_on_its_own():
    # Two of three is not coverage: Kubernetes is nowhere in the CV.
    assert not skill_match(["SQL, Python and Kubernetes"], CV)["covered"]
    assert covered(["SQL and Python"])


def test_alternatives_need_only_one_hit():
    assert covered(["Semantic search / embeddings", "Snowflake or Redshift"])


def test_substring_fallback_respects_word_boundaries():
    # "Go" has no analyzable terms, and a plain substring check finds it inside
    # MongoDB.
    assert not skill_match(["Go"], CV)["covered"]


def test_symbol_only_requirements_still_match():
    assert covered(["C++"], "Studied C++ and Java at university") == {"C++"}


def test_prefix_matching_stops_short_of_a_different_language():
    assert covered(["Postgres"]) == {"Postgres"}      # PostgreSQL
    assert covered(["NodeJS"]) == {"NodeJS"}          # Node.js
    assert not skill_match(["Java"], CV)["covered"]   # not JavaScript


def test_missing_stays_a_list_of_strings_for_the_ui():
    result = skill_match(["Kubernetes", "Python"], CV)
    assert result["missing"] == ["Kubernetes"]
    assert result["missing_detail"] == [
        {"requirement": "Kubernetes", "unmatched": ["kubernetes"]}
    ]


def test_every_covered_requirement_reports_its_evidence():
    for c in skill_match(["Python", "React"], CV)["covered"]:
        assert c["matched"] and all(m["term"] and m["evidence"] for m in c["matched"])


def test_still_deterministic():
    reqs = ["Python", "PostgreSQL", "Kafka"]
    assert skill_match(reqs, CV) == skill_match(reqs, CV)


def test_a_seniority_gate_is_no_longer_reported_as_covered():
    # This used to be a documented limitation: "5+ years" is not a keyword, so
    # the signal reported it covered because the CV mentions backend work. A
    # hand-labelling pass on real postings showed how often that lies, so the
    # signal now declines tenure instead of guessing at it.
    result = skill_match(["5+ years of professional backend experience"], CV)
    assert not result["covered"]
    assert result["not_assessed"] == ["5+ years of professional backend experience"]


def test_traits_a_cv_cannot_evidence_are_not_judged():
    # A person labelling these said "not covered" on every one; the LLM
    # annotator said "covered" on nearly all, because a CV mentioning customers
    # superficially resembles "strong communication". Both are wrong: this
    # signal has nothing to say about them.
    result = skill_match([
        "Strong communication and stakeholder management",
        "Team player with strong interpersonal skills",
        "High accuracy and attention to detail",
        "Excellent written and oral communication",
    ], CV)
    assert result["covered"] == [] and result["missing"] == []
    assert len(result["not_assessed"]) == 4


def test_tenure_is_not_judged_either():
    result = skill_match(["5+ years of professional backend experience"], CV)
    assert result["not_assessed"] == ["5+ years of professional backend experience"]
    assert result["covered"] == []


def test_declining_a_requirement_does_not_dilute_the_score():
    # Two real requirements, one covered: 50%, whatever soft skills surround it.
    result = skill_match(
        ["SQL", "Kubernetes", "Team player", "Excellent written and oral communication"], CV)
    assert result["coverage_score"] == 50
    assert len(result["not_assessed"]) == 2


def test_a_technical_requirement_that_mentions_a_team_is_still_judged():
    # "collaborat" appears here, but the requirement is about a named tool.
    result = skill_match(["Python"], CV)
    assert result["covered"] and not result["not_assessed"]
