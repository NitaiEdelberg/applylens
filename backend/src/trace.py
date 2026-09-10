"""Per-request tracing and structured logs.

Before this, a request went into ApplyLens and nothing came back out about what
happened inside it: four model calls, no record of which of them was slow, what
they cost in tokens, or which model actually answered after the fallback chain
picked one. When production was returning 502s for weeks because Groq retired a
model, the only way to find out was to call the endpoint by hand.

Two ideas, one file:

  Trace   a request id, the stages that ran, and the model calls inside each
          stage. Returned to the caller and rendered in the UI, so latency and
          token cost are visible rather than folklore.
  events  one JSON line per stage, carrying the request id, so a failure in
          production can be found by searching for that id instead of guessed at.

Stages often run concurrently (extract, fit and tailor are gathered), so the
"current stage" is a ContextVar rather than an attribute: asyncio copies the
context into each task, which means every stage sees its own, and an LLM call
attaches its usage to whichever stage it is running under without any of the
services having to pass a trace object around.
"""
import json
import logging
import os
import time
import uuid
from contextvars import ContextVar
from typing import Any, Dict, List, Optional

# Groq prices per million tokens. Unset by default: a made-up price is worse
# than no price, so cost is reported only when the operator supplies real ones.
_PRICE_IN = os.getenv("LLM_PRICE_PER_MTOK_IN", "")
_PRICE_OUT = os.getenv("LLM_PRICE_PER_MTOK_OUT", "")

_trace_var: ContextVar[Optional["Trace"]] = ContextVar("applylens_trace", default=None)
_stage_var: ContextVar[Optional["Stage"]] = ContextVar("applylens_stage", default=None)

log = logging.getLogger("applylens")


def _now_ms() -> float:
    return time.monotonic() * 1000.0


def log_event(event: str, **fields: Any) -> None:
    """One JSON line, always carrying the request id when there is one."""
    trace = _trace_var.get()
    payload = {"event": event}
    if trace is not None:
        payload["request_id"] = trace.request_id
    payload.update(fields)
    log.info(json.dumps(payload, ensure_ascii=False, default=str))


class Stage:
    """One named step of a request, and the model calls made inside it."""

    def __init__(self, name: str):
        self.name = name
        self.started = _now_ms()
        self.ms = 0.0
        self.calls: List[Dict[str, Any]] = []
        self.error: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        out = {"name": self.name, "ms": round(self.ms), "calls": self.calls}
        if self.error:
            out["error"] = self.error
        return out


class Trace:
    def __init__(self, name: str):
        self.request_id = uuid.uuid4().hex[:12]
        self.name = name
        self.started = _now_ms()
        self.stages: List[Stage] = []

    def add(self, stage: Stage) -> None:
        self.stages.append(stage)

    def as_dict(self) -> Dict[str, Any]:
        calls = [c for s in self.stages for c in s.calls]
        prompt_tokens = sum(c.get("prompt_tokens") or 0 for c in calls)
        completion_tokens = sum(c.get("completion_tokens") or 0 for c in calls)
        totals: Dict[str, Any] = {
            "llm_calls": len(calls),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        }
        cost = _cost_usd(prompt_tokens, completion_tokens)
        if cost is not None:
            totals["cost_usd"] = cost
        models = [c.get("model") for c in calls if c.get("model")]
        if models:
            totals["models"] = sorted(set(models))
        return {
            "request_id": self.request_id,
            "name": self.name,
            "total_ms": round(_now_ms() - self.started),
            "stages": [s.as_dict() for s in self.stages],
            "totals": totals,
        }


def _cost_usd(prompt_tokens: int, completion_tokens: int) -> Optional[float]:
    """Dollar cost, or None when nobody has told us the real prices."""
    try:
        price_in, price_out = float(_PRICE_IN), float(_PRICE_OUT)
    except ValueError:
        return None
    cost = (prompt_tokens * price_in + completion_tokens * price_out) / 1_000_000
    return round(cost, 6)


def start_trace(name: str) -> Trace:
    """Begin a trace for this request and make it the ambient one."""
    trace = Trace(name)
    _trace_var.set(trace)
    log_event("request.start", name=name)
    return trace


def current_trace() -> Optional[Trace]:
    return _trace_var.get()


async def traced(name: str, fn, *args, **kwargs):
    """Run one stage of the request, timing it and logging how it ended.

    Awaiting this inside asyncio.gather is the point: each gathered coroutine
    runs in its own task with its own context, so the stage a model call
    attaches itself to is never ambiguous.
    """
    trace = _trace_var.get()
    stage = Stage(name)
    token = _stage_var.set(stage)
    if trace is not None:
        trace.add(stage)
    try:
        result = await fn(*args, **kwargs)
    except Exception as exc:  # recorded, then re-raised untouched
        stage.ms = _now_ms() - stage.started
        stage.error = type(exc).__name__
        log_event("stage.error", stage=name, ms=round(stage.ms), error=str(exc)[:300])
        raise
    else:
        stage.ms = _now_ms() - stage.started
        log_event(
            "stage.ok", stage=name, ms=round(stage.ms),
            llm_calls=len(stage.calls),
            tokens=sum((c.get("prompt_tokens") or 0) + (c.get("completion_tokens") or 0)
                       for c in stage.calls),
        )
        return result
    finally:
        _stage_var.reset(token)


def record_llm_call(model: str, usage: Optional[dict], ms: float,
                    status: int = 200, retried: bool = False) -> None:
    """Attach one model call to whichever stage is running."""
    stage = _stage_var.get()
    call: Dict[str, Any] = {"model": model, "ms": round(ms), "status": status}
    if usage:
        call["prompt_tokens"] = usage.get("prompt_tokens")
        call["completion_tokens"] = usage.get("completion_tokens")
    if retried:
        call["retried"] = True
    if stage is not None:
        stage.calls.append(call)
    log_event("llm.call", stage=stage.name if stage else None, **call)
