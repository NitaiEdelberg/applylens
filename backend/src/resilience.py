"""A circuit breaker for the upstream model API.

When Groq is down, every request still pays the full timeout before failing —
so an outage upstream turns into a pile of slow requests here, and the retry
logic makes it worse by multiplying the calls. The breaker notices a run of
failures and fails the next requests immediately, then lets one through after a
cooldown to see whether the other end came back.

The clock is injectable so the tests can prove the cooldown without sleeping.
"""
import time
from typing import Callable, Optional


class CircuitOpen(Exception):
    """Raised instead of calling an upstream that is currently failing."""


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 4, cooldown_seconds: float = 30.0,
                 clock: Optional[Callable[[], float]] = None):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._clock = clock or time.monotonic
        self._consecutive_failures = 0
        self._opened_at: Optional[float] = None

    @property
    def state(self) -> str:
        """closed = calls flow, open = failing fast, half-open = trying one."""
        if self._opened_at is None:
            return "closed"
        if self._clock() - self._opened_at >= self.cooldown_seconds:
            return "half-open"
        return "open"

    def before_call(self) -> None:
        """Raise CircuitOpen when the upstream should be left alone."""
        if self.state == "open":
            waited = self._clock() - (self._opened_at or 0)
            raise CircuitOpen(
                "upstream failing; retrying in "
                f"{max(0, self.cooldown_seconds - waited):.0f}s"
            )

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        # A half-open probe that fails re-opens the circuit for a fresh cooldown
        # rather than letting the next request through immediately.
        if self.state == "half-open":
            self._opened_at = self._clock()
            return
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.failure_threshold:
            self._opened_at = self._clock()
