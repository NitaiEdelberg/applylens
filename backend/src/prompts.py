"""Prompts as versioned files, so changing one is an experiment, not a guess.

A prompt buried in a function is a prompt nobody can diff, roll back, or
measure. Here each one is a file with a version in its name, the active version
is an environment variable, and evals/run_prompt_ab.py scores two versions
against the same dataset so the winner is chosen by a number.

File format — two labelled sections, because the system prompt is half of the
prompt and hiding it in Python defeats the point:

    ---system---
    You are a strict fact-checker...
    ---user---
    Check these statements against {cv}...

The user section is rendered with str.format, so literal braces in a prompt
must be doubled, exactly as they were when it was an f-string.
"""
import os
import re
from pathlib import Path
from typing import Dict, Tuple

PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"

_SECTION = re.compile(r"^---(system|user)---\s*$", re.MULTILINE)
_cache: Dict[Tuple[str, str], Tuple[str, str]] = {}


def active_version(name: str) -> str:
    """Which version this process is using for `name`."""
    return os.getenv("PROMPT_{}_VERSION".format(name.upper()), "v1")


def load(name: str, version: str = None) -> Tuple[str, str]:
    """(system, user_template) for a prompt version."""
    version = version or active_version(name)
    key = (name, version)
    if key in _cache:
        return _cache[key]

    path = PROMPT_DIR / name / "{}.txt".format(version)
    if not path.exists():
        raise FileNotFoundError(
            "No prompt {}/{}. Available: {}".format(
                name, version,
                ", ".join(sorted(p.stem for p in (PROMPT_DIR / name).glob("*.txt")))
                if (PROMPT_DIR / name).exists() else "none")
        )

    text = path.read_text(encoding="utf-8")
    parts = _SECTION.split(text)
    # parts == ["", "system", <system text>, "user", <user text>]
    sections = {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
    if "system" not in sections or "user" not in sections:
        raise ValueError("{} must contain ---system--- and ---user--- sections".format(path))

    _cache[key] = (sections["system"], sections["user"])
    return _cache[key]


def render(name: str, version: str = None, **fields) -> Tuple[str, str]:
    """(system, user) with the fields substituted into both sections.

    The system section takes fields too: the untrusted-data guard belongs in
    every system prompt, and repeating its wording in each file would let the
    copies drift apart.
    """
    system, template = load(name, version)
    return system.format(**fields), template.format(**fields)


def versions(name: str):
    folder = PROMPT_DIR / name
    return sorted(p.stem for p in folder.glob("*.txt")) if folder.exists() else []
