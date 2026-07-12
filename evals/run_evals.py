"""Evaluate the grounding guardrail against a labeled dataset.

Measures whether check_grounding correctly labels statements as supported vs.
fabricated. Reports accuracy + precision/recall for catching fabrications.

Usage:  GROQ_API_KEY=... python evals/run_evals.py
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# make backend importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from src.services.grounding import check_grounding  # noqa: E402

DATA = Path(__file__).with_name("dataset.jsonl")


async def main():
    if not os.getenv("GROQ_API_KEY"):
        print("Set GROQ_API_KEY to run the evals.")
        return

    rows = [json.loads(line) for line in DATA.read_text().splitlines() if line.strip()]
    # tp/fp/fn are for the "fabrication caught" positive class (supported == False)
    tp = fp = fn = correct = 0

    for row in rows:
        [check] = await check_grounding(row["cv"], [row["statement"]])
        predicted_supported = check["supported"]
        expected_supported = row["expected_supported"]
        if predicted_supported == expected_supported:
            correct += 1
        # fabrication = not supported
        if not expected_supported and not predicted_supported:
            tp += 1
        elif not predicted_supported and expected_supported:
            fp += 1
        elif predicted_supported and not expected_supported:
            fn += 1
        mark = "ok " if predicted_supported == expected_supported else "MISS"
        print(f"[{mark}] supported={predicted_supported} (expected {expected_supported}): {row['statement'][:60]}")

    n = len(rows)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    accuracy = correct / n if n else 0.0
    print("\n--- grounding guardrail ---")
    print(f"accuracy:  {correct}/{n} = {accuracy:.0%}")
    print(f"fabrication precision: {precision:.0%}  recall: {recall:.0%}")

    # Emit a machine-readable summary the frontend can import (T7 trust panel).
    results = {
        "accuracy": round(accuracy, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "n": n,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    payload = json.dumps(results, indent=2) + "\n"
    out = Path(__file__).with_name("results.json")
    out.write_text(payload)
    print(f"wrote {out}")

    # Also bundle a copy the frontend imports at build time (T7 trust panel).
    fe = Path(__file__).resolve().parents[1] / "frontend" / "src" / "eval-results.json"
    if fe.parent.exists():
        fe.write_text(payload)
        print(f"wrote {fe}")


if __name__ == "__main__":
    asyncio.run(main())
