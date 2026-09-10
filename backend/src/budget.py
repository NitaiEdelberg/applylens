"""A ceiling on what one request may spend, and what to drop when it is hit.

Analyze runs four model calls, and on a slow upstream that adds up to a minute
of someone watching a spinner, or to a token bill nobody is counting. The
answer is not a timeout — a timeout throws away the work already done and shows
an error. It is to spend the budget on the parts that matter most and skip the
parts that matter least, then say what was skipped.

Order of sacrifice, cheapest loss first:

  1. cover-letter grounding   the cover letter is a draft to edit; its claims
                              matter less than the bullets people paste as-is.
  2. bullet grounding         never skipped. It is the guardrail, and a result
                              that silently stopped being fact-checked would be
                              worse than a slow one.

Nothing here raises. A budget that fails a request is just a timeout with extra
steps.
"""
import os

from .trace import current_trace

MAX_SECONDS = float(os.getenv("ANALYZE_BUDGET_SECONDS", "75"))
MAX_TOKENS = int(os.getenv("ANALYZE_BUDGET_TOKENS", "24000"))


def spent():
    """(seconds, tokens) used by the current request so far."""
    trace = current_trace()
    if trace is None:
        return 0.0, 0
    snapshot = trace.as_dict()
    totals = snapshot["totals"]
    return snapshot["total_ms"] / 1000.0, totals["prompt_tokens"] + totals["completion_tokens"]


def over_budget():
    """Why the request is out of budget, or None while it still has room."""
    seconds, tokens = spent()
    if seconds >= MAX_SECONDS:
        return "{:.0f}s spent of a {:.0f}s budget".format(seconds, MAX_SECONDS)
    if tokens >= MAX_TOKENS:
        return "{:,} tokens spent of a {:,} budget".format(tokens, MAX_TOKENS)
    return None
