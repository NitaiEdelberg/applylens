"""The breaker's whole job is timing, so the clock is injected and no test sleeps."""
import pytest

from src.resilience import CircuitBreaker, CircuitOpen


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


def test_it_stays_closed_while_calls_succeed():
    breaker = CircuitBreaker(failure_threshold=2, clock=Clock())
    for _ in range(5):
        breaker.before_call()
        breaker.record_success()
    assert breaker.state == "closed"


def test_a_success_clears_earlier_failures():
    breaker = CircuitBreaker(failure_threshold=3, clock=Clock())
    breaker.record_failure()
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()
    assert breaker.state == "closed", "two old failures plus one new is not a streak"


def test_it_opens_after_the_threshold_and_fails_fast():
    breaker = CircuitBreaker(failure_threshold=2, clock=Clock())
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.state == "open"
    with pytest.raises(CircuitOpen):
        breaker.before_call()


def test_it_lets_one_call_through_after_the_cooldown():
    clock = Clock()
    breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=30, clock=clock)
    breaker.record_failure()
    clock.advance(29)
    with pytest.raises(CircuitOpen):
        breaker.before_call()
    clock.advance(2)
    assert breaker.state == "half-open"
    breaker.before_call()  # the probe is allowed


def test_a_failed_probe_starts_a_fresh_cooldown():
    clock = Clock()
    breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=30, clock=clock)
    breaker.record_failure()
    clock.advance(31)
    breaker.before_call()
    breaker.record_failure()  # the probe failed too
    assert breaker.state == "open"
    clock.advance(29)
    with pytest.raises(CircuitOpen):
        breaker.before_call()


def test_a_successful_probe_closes_the_circuit():
    clock = Clock()
    breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=30, clock=clock)
    breaker.record_failure()
    clock.advance(31)
    breaker.before_call()
    breaker.record_success()
    assert breaker.state == "closed"


def test_the_message_says_how_long_to_wait():
    clock = Clock()
    breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=30, clock=clock)
    breaker.record_failure()
    clock.advance(10)
    with pytest.raises(CircuitOpen) as exc:
        breaker.before_call()
    assert "20s" in str(exc.value)
