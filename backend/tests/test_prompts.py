"""Prompts are files now, so these are the things a file can get wrong."""
import pytest

from src import prompts


def test_both_tailor_versions_exist():
    assert prompts.versions("tailor") == ["v1", "v2"]


def test_rendering_fills_the_job_and_cv():
    system, user = prompts.render("tailor", "v1", guard="GUARD", job="JOB", cv="CV")
    assert "JOB" in user and "CV" in user
    assert "resume writer" in system.lower()


def test_the_untrusted_guard_reaches_the_system_prompt():
    # Every prompt shares one guard string; duplicating its wording per file is
    # how the copies drift apart.
    system, _ = prompts.render("tailor", "v2", guard="THE-GUARD", job="j", cv="c")
    assert "THE-GUARD" in system
    assert "{guard}" not in system


def test_literal_json_braces_survive_rendering():
    _, user = prompts.render("tailor", "v1", guard="g", job="j", cv="c")
    assert '{"bullets": [str], "cover_letter": str}' in user


def test_the_active_version_comes_from_the_environment(monkeypatch):
    assert prompts.active_version("tailor") == "v1"
    monkeypatch.setenv("PROMPT_TAILOR_VERSION", "v2")
    assert prompts.active_version("tailor") == "v2"


def test_a_missing_version_says_which_ones_exist():
    with pytest.raises(FileNotFoundError) as exc:
        prompts.load("tailor", "v99")
    assert "v1" in str(exc.value) and "v2" in str(exc.value)


def test_a_missing_field_fails_loudly_rather_than_shipping_a_hole():
    with pytest.raises(KeyError):
        prompts.render("tailor", "v1", guard="g", job="j")  # no cv
