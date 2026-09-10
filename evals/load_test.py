"""What happens when several analyses run at once.

Nobody had ever run two of these concurrently. The service is one free 512 MB
instance running four model calls per request, and "it works when I click it"
says nothing about what the second person clicking it experiences.

Point it at a locally running server in cassette-replay mode and the whole test
is free, deterministic and offline — no key, no tokens, no rate limit — which
measures exactly the thing this server controls: its own concurrency,
serialisation and memory behaviour. Point it at production instead and you are
mostly measuring Groq's rate limiter, which is worth knowing once and not worth
running twice.

    # terminal 1
    LLM_CASSETTE=evals/cassettes/analyze.jsonl LLM_CASSETTE_MODE=replay \\
      uvicorn src.server:app --port 8000

    # terminal 2
    python evals/load_test.py --concurrency 10 --requests 30
"""
import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "load_results.json"


def percentile(values, pct):
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((pct / 100) * (len(ordered) - 1))))
    return ordered[index]


async def one_request(client, url, body, index):
    started = time.monotonic()
    try:
        # Vary the CV slightly per request so the analysis cache does not turn a
        # load test into a test of a dictionary lookup.
        payload = dict(body, cv_text=body["cv_text"] + "\nRequest {}.".format(index))
        response = await client.post(url, json=payload)
        elapsed = time.monotonic() - started
        return {"ok": response.status_code == 200, "status": response.status_code,
                "seconds": elapsed}
    except Exception as exc:  # noqa: BLE001 — a failed request is a result
        return {"ok": False, "status": 0, "seconds": time.monotonic() - started,
                "error": type(exc).__name__}


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--requests", type=int, default=30)
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args()

    body = {
        "jd_text": ("Solutions Engineer, AI. Requirements: Python, SQL against a cloud "
                    "warehouse, customer-facing experience, 2+ years with LLMs."),
        "cv_text": ("AI Solutions Engineer at Jigso: built LLM-powered features, wrote SQL "
                    "against Snowflake and BigQuery, worked directly with customers."),
    }
    url = args.base.rstrip("/") + "/api/analyze"
    gate = asyncio.Semaphore(args.concurrency)

    async with httpx.AsyncClient(timeout=args.timeout) as client:
        try:
            health = await client.get(args.base.rstrip("/") + "/health", timeout=10)
            print("health: {}".format(health.json()))
        except Exception as exc:  # noqa: BLE001
            print("Cannot reach {}: {}".format(args.base, exc))
            return 1

        async def guarded(index):
            async with gate:
                return await one_request(client, url, body, index)

        print("{} requests, {} at a time\n".format(args.requests, args.concurrency))
        started = time.monotonic()
        results = await asyncio.gather(*(guarded(i) for i in range(args.requests)))
        wall = time.monotonic() - started

    ok = [r for r in results if r["ok"]]
    failed = [r for r in results if not r["ok"]]
    times = [r["seconds"] for r in ok]

    print("{}/{} succeeded in {:.1f}s ({:.2f} requests/second)".format(
        len(ok), len(results), wall, len(results) / wall if wall else 0))
    if times:
        print("latency  p50 {:.2f}s  p90 {:.2f}s  p99 {:.2f}s  max {:.2f}s  mean {:.2f}s".format(
            percentile(times, 50), percentile(times, 90), percentile(times, 99),
            max(times), statistics.mean(times)))
    if failed:
        by_status = {}
        for row in failed:
            key = row.get("error") or "HTTP {}".format(row["status"])
            by_status[key] = by_status.get(key, 0) + 1
        print("\nfailures: " + ", ".join("{} x{}".format(k, v) for k, v in by_status.items()))
        print("What fails first is the finding. 429 means the model API's limit, "
              "503 means the circuit breaker did its job, a timeout or a dropped "
              "connection means this box ran out of room.")
    else:
        print("\nNo failures. The ceiling is above this level of concurrency.")

    RESULTS.write_text(json.dumps({
        "base": args.base, "concurrency": args.concurrency, "requests": args.requests,
        "wall_seconds": wall, "succeeded": len(ok), "failed": len(failed),
        "p50": percentile(times, 50), "p90": percentile(times, 90),
        "p99": percentile(times, 99), "results": results,
    }, indent=2), encoding="utf-8")
    print("wrote {}".format(RESULTS.name))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
