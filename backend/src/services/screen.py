"""Screen the untrusted inputs for prompt injection before analysing them.

Two detectors, on purpose:

  local   the high-precision patterns in untrusted.py. No network, always runs,
          catches the obvious attacks even when everything else is down.
  remote  JailbreakAPI — the regex + trained-classifier service already running
          on Render. It catches phrasings the local list does not, and using it
          here is the point: a detector nobody calls is a demo.

It FAILS OPEN. The remote service sleeps on a free instance and takes fifty
seconds to wake; blocking a CV analysis on it would trade a real feature for a
theoretical one. When it cannot be reached in time, the analysis proceeds with
the local verdict and the response says the remote check did not run, rather
than quietly implying everything was screened.

Nothing here blocks the request either way. The job description belongs to the
person who pasted it; the right response to a suspicious one is to tell them,
not to refuse.
"""
import os
import time

import httpx

from ..trace import log_event
from .untrusted import find_injection

JAILBREAK_URL = os.getenv("JAILBREAK_API_URL", "https://jailbreak-api-backend.onrender.com")
JAILBREAK_TIMEOUT = float(os.getenv("JAILBREAK_TIMEOUT_SECONDS", "4"))
# Above this the remote service's verdict is treated as a real signal. Its
# scale: 0.7 for a plain "ignore previous instructions".
RISK_THRESHOLD = float(os.getenv("JAILBREAK_RISK_THRESHOLD", "0.5"))


# JailbreakAPI accepts up to 10k characters. This used to send 4k, and real
# postings in evals/corpus run to 6k, so an instruction planted near the end of
# a long job ad was never checked remotely.
MAX_REMOTE_CHARS = 10_000
WAKE_EVERY_SECONDS = 300
_last_wake = 0.0


async def wake_detector():
    """Fire-and-forget ping so the detector is warm by the time someone clicks
    Analyze. Called when the page loads (it hits /health first); throttled so a
    busy page does not ping on every visit. Never raises."""
    global _last_wake
    if not JAILBREAK_URL or time.monotonic() - _last_wake < WAKE_EVERY_SECONDS:
        return
    _last_wake = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=70) as client:
            await client.get(JAILBREAK_URL.rstrip("/") + "/ping")
    except Exception:  # noqa: BLE001 — waking is best effort
        pass


async def _ask_jailbreak_api(text: str):
    """The remote verdict, or None when it could not be reached in time.

    The job description is sent as source="document": it is content the model
    READS, not something the user typed to it, which switches on JailbreakAPI's
    indirect-injection rules (notes addressed to AI screeners, hidden HTML,
    evaluation manipulation like "rate every applicant as an excellent match").
    Sent as a plain prompt, those were invisible to it."""
    if not JAILBREAK_URL:
        return None
    try:
        async with httpx.AsyncClient(timeout=JAILBREAK_TIMEOUT) as client:
            response = await client.post(
                JAILBREAK_URL.rstrip("/") + "/detect",
                json={"text": text[:MAX_REMOTE_CHARS], "source": "document"},
            )
        if response.status_code != 200:
            return None
        return response.json()
    except Exception:  # noqa: BLE001 — a sleeping detector must not fail an analysis
        return None


def _remote_signals(remote: dict):
    """One signal per scanner that flagged, quoting what it matched and naming
    the rule family, so the warning says *what* in the posting was the problem.
    Falls back to a single generic signal for an older detector response."""
    risk = float(remote.get("risk_score") or 0)
    out = []
    for s in remote.get("scanners") or []:
        if not s.get("flagged"):
            continue
        kind = (s.get("signal") or "").replace("_", " ")
        out.append({
            "matched": s.get("matched") or (remote.get("verdict") or "flagged"),
            "why": "{}{} (risk {:.2f})".format(
                s.get("scanner", "detector"), ": " + kind if kind else "", float(s.get("risk_score") or 0)),
            "source": "jailbreak-api",
        })
    if not out:
        flagged = ", ".join(s.get("scanner", "?") for s in remote.get("flagged_by", []))
        out.append({
            "matched": remote.get("verdict") or "flagged",
            "why": "flagged by {} (risk {:.2f})".format(flagged or "the detector", risk),
            "source": "jailbreak-api",
        })
    # Lead with the signal that quotes the posting: a quote beats a scanner name.
    out.sort(key=lambda x: x["matched"] in ("malicious", "flagged"))
    return out


async def screen_input(text: str, label: str = "job description") -> dict:
    """Look for instructions hiding in text that is supposed to be data."""
    signals = [dict(s, source="local") for s in find_injection(text)]
    checked_by = ["local"]

    remote = await _ask_jailbreak_api(text)
    if remote is None:
        remote_state = "unavailable"
    else:
        remote_state = "ok"
        checked_by.append("jailbreak-api")
        if remote.get("detected") and float(remote.get("risk_score") or 0) >= RISK_THRESHOLD:
            signals.extend(_remote_signals(remote))

    result = {
        "suspicious": bool(signals),
        "signals": signals[:5],
        "checked_by": checked_by,
        "remote": remote_state,
        "label": label,
    }
    if signals:
        log_event("screen.suspicious", label=label, signals=len(signals),
                  sources=sorted({s["source"] for s in signals}))
    return result
