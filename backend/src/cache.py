"""A small in-process cache for whole analyses.

The same CV against the same job runs four model calls again and returns the
same answer, which costs tokens and about half a minute. That happens more than
it sounds: someone tweaks one line of their CV and re-runs, a demo runs twice,
two people paste the same public job ad.

In-process on purpose. One free instance serves this app, so a shared cache
would mean adding Redis to save four calls; when the instance sleeps, the cache
goes with it, which is the correct behaviour for a convenience.

The clock is injectable so expiry can be tested without sleeping.
"""
import hashlib
import re
import time
from collections import OrderedDict
from typing import Any, Callable, Optional

_WHITESPACE = re.compile(r"\s+")


def fingerprint(*parts: Optional[str]) -> str:
    """A stable key for a set of text inputs.

    Whitespace and case are normalised first: a CV that differs only by a
    trailing newline or a capitalised heading is the same CV as far as the model
    is concerned, and treating it as a new one defeats the point.
    """
    digest = hashlib.sha256()
    for part in parts:
        normalised = _WHITESPACE.sub(" ", (part or "").strip().lower())
        digest.update(normalised.encode("utf-8"))
        digest.update(b"\x00")  # keep the fields from bleeding into each other
    return digest.hexdigest()[:32]


class ResultCache:
    def __init__(self, max_entries: int = 64, ttl_seconds: float = 3600.0,
                 clock: Optional[Callable[[], float]] = None):
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self._clock = clock or time.monotonic
        self._entries: "OrderedDict[str, Any]" = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, key: str):
        entry = self._entries.get(key)
        if entry is None:
            self.misses += 1
            return None
        stored_at, value = entry
        if self._clock() - stored_at > self.ttl_seconds:
            del self._entries[key]
            self.misses += 1
            return None
        self._entries.move_to_end(key)  # keep what people actually re-run
        self.hits += 1
        return value

    def set(self, key: str, value: Any) -> None:
        self._entries[key] = (self._clock(), value)
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        self._entries.clear()

    @property
    def size(self) -> int:
        return len(self._entries)
