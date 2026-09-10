"""What the analysis cache must and must not treat as the same request."""
from src.cache import ResultCache, fingerprint


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


def test_cosmetic_differences_are_the_same_request():
    assert fingerprint("Python  developer\n") == fingerprint("python developer")


def test_the_fields_do_not_bleed_into_each_other():
    # "ab" + "c" must not collide with "a" + "bc", or one person's CV could be
    # served another person's analysis.
    assert fingerprint("ab", "c") != fingerprint("a", "bc")


def test_different_inputs_are_different_requests():
    assert fingerprint("jd", "cv-a") != fingerprint("jd", "cv-b")


def test_a_stored_result_comes_back():
    cache = ResultCache(clock=Clock())
    cache.set("k", {"score": 71})
    assert cache.get("k") == {"score": 71}
    assert (cache.hits, cache.misses) == (1, 0)


def test_a_missing_key_is_a_miss_not_an_error():
    cache = ResultCache(clock=Clock())
    assert cache.get("nope") is None
    assert cache.misses == 1


def test_entries_expire():
    clock = Clock()
    cache = ResultCache(ttl_seconds=60, clock=clock)
    cache.set("k", "v")
    clock.advance(59)
    assert cache.get("k") == "v"
    clock.advance(2)
    assert cache.get("k") is None
    assert cache.size == 0, "an expired entry is dropped, not just hidden"


def test_the_oldest_unused_entry_is_evicted_first():
    cache = ResultCache(max_entries=2, clock=Clock())
    cache.set("a", 1)
    cache.set("b", 2)
    cache.get("a")          # "a" is the one people keep re-running
    cache.set("c", 3)
    assert cache.get("a") == 1
    assert cache.get("b") is None
    assert cache.get("c") == 3
