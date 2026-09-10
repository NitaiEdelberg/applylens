"""Strip personal details out of a CV before it leaves this server.

A CV is one of the most identifying documents a person owns, and this product
sends it to a third-party API to be analysed. None of the analysis needs the
phone number: the fit score, the tailored bullets and the grounding check all
work exactly as well on a CV whose contact block has been replaced with
placeholders. So the details are swapped out on the way to the model and put
back on the way to the screen, and the person's phone number never leaves the
box.

What is NOT redacted, and why:

  the person's name  Detecting names without a full NER model means guessing
                     from capitalisation, which mangles job titles and company
                     names and would corrupt the grounding evidence. The name
                     is also the least sensitive item in the block.
  employers, schools These are the substance of the analysis. Removing them
                     would make the fit score meaningless.
  github/portfolio   Public professional links the candidate published on
                     purpose.

Placeholders are stable within one document (the same email is always
[EMAIL_1]) so the model can still reason about "the contact address" and so
restoring is exact.
"""
import re
from typing import Dict, Tuple

# Ordered: the first pattern that claims a span keeps it, so URLs are matched
# before bare emails and long numbers before short ones.
_PATTERNS = [
    ("URL", re.compile(
        r"\bhttps?://(?:www\.)?(?:linkedin\.com|facebook\.com|instagram\.com|x\.com|twitter\.com)"
        r"/[^\s,;)\]]+", re.IGNORECASE)),
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    # Israeli mobile (050-123-4567, +972 50 1234567) and generic international.
    ("PHONE", re.compile(
        r"(?<![\w-])(?:\+?\d{1,3}[\s.-]?)?(?:\(0?\d{1,4}\)|0?\d{1,4})[\s.-]?\d{3}[\s.-]?\d{4}"
        r"(?![\w-])")),
    # Israeli teudat zehut and similar national ids: 9 digits standing alone.
    ("ID", re.compile(r"(?<![\w./-])\d{9}(?![\w./-])")),
    ("ADDRESS", re.compile(
        r"\b\d{1,4}\s+[A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+)*\s+"
        r"(?:Street|St\.?|Road|Rd\.?|Avenue|Ave\.?|Boulevard|Blvd\.?|Lane|Ln\.?|Drive|Dr\.?)"
        r"(?:,?\s*(?:Apt|Suite|Unit)\.?\s*\d+[A-Za-z]?)?", re.IGNORECASE)),
    ("DOB", re.compile(
        r"\b(?:date of birth|d\.?o\.?b\.?|born)\s*[:\-]?\s*"
        r"\d{1,4}[./-]\d{1,2}[./-]\d{1,4}", re.IGNORECASE)),
]


def redact(text: str) -> Tuple[str, Dict[str, str]]:
    """Return the text with personal details replaced, and how to put them back."""
    if not text:
        return text or "", {}

    mapping: Dict[str, str] = {}
    seen: Dict[str, str] = {}
    counters: Dict[str, int] = {}
    out = text

    for kind, pattern in _PATTERNS:
        def swap(match, kind=kind):
            value = match.group(0)
            if value in seen:
                return seen[value]
            counters[kind] = counters.get(kind, 0) + 1
            placeholder = "[{}_{}]".format(kind, counters[kind])
            seen[value] = placeholder
            mapping[placeholder] = value
            return placeholder

        out = pattern.sub(swap, out)

    return out, mapping


def restore(text: str, mapping: Dict[str, str]) -> str:
    """Put the real values back into one string."""
    if not text or not mapping:
        return text
    for placeholder, value in mapping.items():
        text = text.replace(placeholder, value)
    return text


def restore_deep(obj, mapping: Dict[str, str]):
    """Put the real values back everywhere in a nested response.

    A placeholder can surface anywhere the model quoted the CV: a bullet, a
    piece of grounding evidence, the cover letter. Walking the whole structure
    is cheaper than trying to remember which fields those are.
    """
    if not mapping:
        return obj
    if isinstance(obj, str):
        return restore(obj, mapping)
    if isinstance(obj, list):
        return [restore_deep(item, mapping) for item in obj]
    if isinstance(obj, dict):
        return {key: restore_deep(value, mapping) for key, value in obj.items()}
    return obj


def summary(mapping: Dict[str, str]) -> Dict[str, int]:
    """How many of each kind were removed — for the privacy note in the UI."""
    counts: Dict[str, int] = {}
    for placeholder in mapping:
        kind = placeholder.strip("[]").rsplit("_", 1)[0].lower()
        counts[kind] = counts.get(kind, 0) + 1
    return counts
