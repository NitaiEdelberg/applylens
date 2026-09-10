"""Record real model responses once, replay them forever.

The evals that matter — does the guardrail catch a fabricated bullet, does the
fit score stay stable when a prompt changes — need real model output. That
makes them exactly the tests that never run in CI: they need a key, they cost
money, they are slow, and they fail for reasons that have nothing to do with
the commit.

A cassette fixes that the way HTTP fixtures always have. Run once against the
real API in record mode, commit the tape, and every run after that replays it:
no key, no bill, no flakiness, and a diff on the tape shows exactly what the
model started saying differently.

The key is the request, not the model id, so the fallback chain picking a
different model does not invalidate a tape. What that costs is honesty about
which model produced the recording, so each entry records it.

A miss in replay mode is a loud error, never a silent live call: a cassette
that quietly falls through to the network is worse than no cassette, because
the CI job that "passed" was a network call you did not know you made.
"""
import hashlib
import json
import os
import threading
from typing import Optional

MODE = os.getenv("LLM_CASSETTE_MODE", "off")  # off | record | replay
PATH = os.getenv("LLM_CASSETTE", "")

_lock = threading.Lock()
_entries = None  # lazy: {key: entry}


class CassetteMiss(Exception):
    """Replay was asked for a request the tape does not contain."""


def enabled() -> bool:
    return MODE in ("record", "replay") and bool(PATH)


def key_for(messages, temperature, response_format) -> str:
    """Identify a request by what was asked, not by who answered it."""
    payload = json.dumps(
        {
            "messages": messages,
            "temperature": round(float(temperature), 3),
            "format": (response_format or {}).get("type") if response_format else None,
        },
        sort_keys=True, ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _load():
    global _entries
    if _entries is not None:
        return _entries
    _entries = {}
    if PATH and os.path.exists(PATH):
        with open(PATH, encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    entry = json.loads(line)
                    _entries[entry["key"]] = entry
    return _entries


def playback(key: str) -> Optional[str]:
    """The recorded reply for this request, or raise if the tape lacks it."""
    entry = _load().get(key)
    if entry is None:
        raise CassetteMiss(
            "No recording for this request in {}. Re-record with "
            "LLM_CASSETTE_MODE=record and a real key, then commit the tape.".format(PATH)
        )
    return entry["content"]


def record(key: str, content: str, model: str, usage=None, note: str = "") -> None:
    """Append one exchange to the tape. Re-recording the same request replaces it."""
    if not PATH:
        return
    entry = {"key": key, "model": model, "content": content,
             "usage": usage or {}, "note": note}
    with _lock:
        existing = _load()
        existing[key] = entry
        directory = os.path.dirname(PATH)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(PATH, "w", encoding="utf-8") as handle:
            for value in existing.values():
                handle.write(json.dumps(value, ensure_ascii=False) + "\n")


def stats():
    return {"mode": MODE, "path": PATH, "entries": len(_load()) if PATH else 0}
