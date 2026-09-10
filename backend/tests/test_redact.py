"""What must never reach the third-party API, and what must survive the trip."""
from src.services.redact import redact, restore, restore_deep, summary

CV = """Nitai Edelberg
nitai.edel@gmail.com | 054-123-4567 | https://linkedin.com/in/nitai-edelberg
12 Herzl Street, Apt 4, Tel Aviv

AI Solutions Engineer at Jigso. Wrote SQL against Snowflake and BigQuery.
B.Sc. Computer Science, Ben-Gurion University."""


def test_contact_details_do_not_reach_the_model():
    clean, mapping = redact(CV)
    for secret in ["nitai.edel@gmail.com", "054-123-4567", "linkedin.com/in/nitai-edelberg"]:
        assert secret not in clean
    assert mapping


def test_the_substance_of_the_cv_survives():
    clean, _ = redact(CV)
    for kept in ["Jigso", "Snowflake", "BigQuery", "Ben-Gurion University",
                 "AI Solutions Engineer"]:
        assert kept in clean, "the analysis is about exactly this text"


def test_the_name_is_deliberately_kept():
    # Documented decision: guessing names from capitalisation mangles job
    # titles and company names, and corrupts the grounding evidence.
    clean, _ = redact(CV)
    assert "Nitai Edelberg" in clean


def test_the_same_value_gets_the_same_placeholder():
    clean, mapping = redact("a@b.com wrote to a@b.com and to c@d.com")
    assert clean.count("[EMAIL_1]") == 2
    assert "[EMAIL_2]" in clean
    assert len(mapping) == 2


def test_restoring_gives_the_original_back():
    clean, mapping = redact(CV)
    assert restore(clean, mapping) == CV


def test_placeholders_are_restored_wherever_the_model_quoted_them():
    clean, mapping = redact(CV)
    response = {
        "bullets": ["Reachable at " + clean.split("|")[1].strip()],
        "grounding": [{"evidence": clean, "supported": True}],
        "score": 71,
    }
    restored = restore_deep(response, mapping)
    assert "054-123-4567" in restored["bullets"][0]
    assert "nitai.edel@gmail.com" in restored["grounding"][0]["evidence"]
    assert restored["score"] == 71


def test_a_cv_with_nothing_to_hide_is_untouched():
    text = "Backend engineer. Python, FastAPI, PostgreSQL."
    clean, mapping = redact(text)
    assert clean == text and mapping == {}


def test_empty_input_does_not_raise():
    assert redact("") == ("", {})
    assert redact(None)[0] == ""
    assert restore("x", {}) == "x"


def test_an_id_number_is_removed_but_a_year_is_not():
    clean, _ = redact("ID 123456789, graduated 2024, 3+ years experience")
    assert "123456789" not in clean
    assert "2024" in clean and "3+ years" in clean


def test_the_summary_counts_what_was_removed():
    _, mapping = redact(CV)
    counts = summary(mapping)
    assert counts.get("email") == 1
    assert counts.get("phone") == 1
