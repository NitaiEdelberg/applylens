"""Ask the live site to do the one thing it exists for, and say if it can't.

Three mornings in a row this app was broken and a person found out by trying
it. Every one of those failures — a retired model, a daily token cap, a
tool-call wrapper from constrained decoding — was invisible to the unit tests,
because every one of them lived in the space between this code and somebody
else's API. That space needs a test that runs against the real thing.

So: one real analysis against production, on a schedule. It checks the answer
is actually an answer — a fit score, bullets, a grounding verdict per bullet —
rather than a 200 with an empty body, and prints the trace so a slow run can be
read afterwards rather than guessed at.

Costs about three thousand tokens per run, which on a free tier is a real
consideration: twice a day is affordable, every five minutes is not.

    python evals/smoke_prod.py
    python evals/smoke_prod.py --base http://127.0.0.1:8000
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

DEFAULT_BASE = "https://applylens-backend.onrender.com"

JD = ("Solutions Engineer, AI. You will work with enterprise customers to deploy "
      "LLM-powered features and write SQL against their cloud data warehouse. "
      "Requirements: strong Python; SQL; customer-facing experience; 2+ years with "
      "LLMs. Nice to have: Kubernetes, Terraform, React.")
CV = ("AI Solutions Engineer at Jigso: built LLM-powered features and the tooling "
      "around them, wrote SQL against Snowflake and BigQuery, and worked directly "
      "with customers. Projects: a prompt-injection detection API in FastAPI with "
      "scikit-learn. B.Sc. Computer Science, Ben-Gurion University.")


def post(url, payload, timeout):
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def check(result):
    """What has to be true for this to count as working. Returns the failures."""
    problems = []
    fit = result.get("fit") or {}
    if not isinstance(fit.get("overall_score"), int):
        problems.append("no fit score")
    tailor = result.get("tailor") or {}
    bullets = tailor.get("bullets") or []
    if len(bullets) < 2:
        problems.append("only {} bullets".format(len(bullets)))
    grounding = tailor.get("grounding") or []
    if len(grounding) != len(bullets):
        problems.append("{} bullets but {} grounding verdicts — the guardrail "
                        "did not see them all".format(len(bullets), len(grounding)))
    job = result.get("job") or {}
    if not (job.get("must_haves") or []):
        problems.append("no requirements extracted")
    match = result.get("skill_match") or {}
    if not match.get("covered") and not match.get("missing"):
        problems.append("the deterministic signal produced nothing")
    return problems


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--timeout", type=float, default=180,
                        help="generous: a sleeping free instance takes ~50s to wake")
    args = parser.parse_args()
    base = args.base.rstrip("/")

    started = time.time()
    try:
        # Wake it first, so the analyze timeout measures the analysis and not
        # the cold start.
        with urllib.request.urlopen(base + "/health", timeout=args.timeout) as response:
            print("health: {} after {:.1f}s".format(response.status, time.time() - started))
    except Exception as exc:  # noqa: BLE001
        print("FAIL: the server did not answer /health: {}".format(exc))
        return 1

    # One retry, and only for errors that are plausibly transient (a 5xx while
    # the instance finishes booting, a 429 from the model provider, a timeout).
    # It is printed, so a flaky day is still visible; it just does not email a
    # failure for a single blip. A 4xx or a wrong answer is never retried.
    for attempt in (1, 2):
        started = time.time()
        try:
            status, result = post(base + "/api/analyze",
                                  {"jd_text": JD, "cv_text": CV}, args.timeout)
            break
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "ignore")[:400]
            msg = "/api/analyze returned {} after {:.1f}s\n  {}".format(
                exc.code, time.time() - started, body)
            transient = exc.code >= 500 or exc.code == 429
        except Exception as exc:  # noqa: BLE001
            msg = "/api/analyze did not answer in {:.0f}s: {}".format(args.timeout, exc)
            transient = True
        if attempt == 1 and transient:
            print("retrying once in 30s after: " + msg)
            time.sleep(30)
            continue
        print("FAIL: " + msg)
        return 1

    elapsed = time.time() - started
    problems = check(result)

    trace = result.get("trace") or {}
    totals = trace.get("totals") or {}
    print("analyze: {} in {:.1f}s".format(status, elapsed))
    print("  fit {} | {} bullets, {} flagged | coverage {}".format(
        (result.get("fit") or {}).get("overall_score"),
        len((result.get("tailor") or {}).get("bullets") or []),
        (result.get("tailor") or {}).get("flagged_count"),
        (result.get("skill_match") or {}).get("coverage_score")))
    if trace:
        print("  request {} | {} | {} model calls, {} tokens".format(
            trace.get("request_id"), ", ".join(totals.get("models") or []) or "?",
            totals.get("llm_calls"), (totals.get("prompt_tokens") or 0)
            + (totals.get("completion_tokens") or 0)))
        print("  stages: " + ", ".join("{} {:.1f}s".format(s["name"], s["ms"] / 1000)
                                       for s in trace.get("stages") or []))
    for step in (result.get("tailor") or {}).get("degraded") or []:
        print("  degraded: {} ({})".format(step.get("step"), step.get("reason")))

    if problems:
        print("\nFAIL: " + "; ".join(problems))
        return 1
    print("\nPASS")
    return 0


class _Tee:
    """Print as usual and keep a copy, so a failure can be written somewhere
    readable without a GitHub login (see below)."""

    def __init__(self, stream):
        self.stream, self.lines = stream, []

    def write(self, text):
        self.lines.append(text)
        return self.stream.write(text)

    def flush(self):
        self.stream.flush()


if __name__ == "__main__":
    tee = _Tee(sys.stdout)
    sys.stdout = tee
    code = main()
    sys.stdout = tee.stream
    # Action logs need a login to read; the job summary does not (it is exposed
    # through the public check-runs API). Three scheduled failures went
    # undiagnosed because the reason only lived in the log. Put it here too.
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if code and summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("### Production smoke test failed\n```\n" + "".join(tee.lines)[-3000:] + "\n```\n")
    sys.exit(code)
