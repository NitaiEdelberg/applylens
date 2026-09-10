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

import httpx

from ..trace import log_event
from .untrusted import find_injection

JAILBREAK_URL = os.getenv("JAILBREAK_API_URL", "https://jailbreak-api-backend.onrender.com")
JAILBREAK_TIMEOUT = float(os.getenv("JAILBREAK_TIMEOUT_SECONDS", "4"))
# Above this the remote service's verdict is treated as a real signal. Its
# scale: 0.7 for a plain "ignore previous instructions".
RISK_THRESHOLD = float(os.getenv("JAILBREAK_RISK_THRESHOLD", "0.5"))


async def _ask_jailbreak_api(text: str):
    """The remote verdict, or None when it could not be reached in time."""
    if not JAILBREAK_URL:
        return None
    try:
        async with httpx.AsyncClient(timeout=JAILBREAK_TIMEOUT) as client:
            response = await client.post(
                JAILBREAK_URL.rstrip("/") + "/detect", json={"text": text[:4000]}
            )
        if response.status_code != 200:
            return None
        return response.json()
    except Exception:  # noqa: BLE001 — a sleeping detector must not fail an analysis
        return None


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
            flagged = ", ".join(s.get("scanner", "?") for s in remote.get("flagged_by", []))
            signals.append({
                "matched": (remote.get("verdict") or "flagged"),
                "why": "flagged by {} (risk {:.2f})".format(
                    flagged or "the detector", float(remote.get("risk_score") or 0)),
                "source": "jailbreak-api",
            })

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
