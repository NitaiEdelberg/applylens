"""Evaluate the grounding guardrail against a labelled dataset.

The guardrail is what makes this product safe to use: it decides whether a
generated bullet is backed by the CV. This measures how often it is right, in
both directions, because the two errors cost different things. Missing a
fabrication puts an invented claim on someone's resume. Flagging a true
statement nags them about a real achievement.

    python evals/run_evals.py --record    # once, with a real key: writes the tape
    python evals/run_evals.py --replay    # any time, no key, no bill: reads it
    python evals/run_evals.py             # live, against the real API

Replay is what runs in CI. It is not a substitute for re-recording: when a
prompt changes, the tape has to be re-cut, and the diff shows exactly what the
model started saying differently.
"""
import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
TAPE = HERE / "cassettes" / "grounding.jsonl"

# Parsed before importing the client, which reads its config at import time.
_args = argparse.ArgumentParser(add_help=False)
_args.add_argument("--record", action="store_true")
_args.add_argument("--replay", action="store_true")
_known, _ = _args.parse_known_args()
if _known.record or _known.replay:
    os.environ["LLM_CASSETTE"] = str(TAPE)
    os.environ["LLM_CASSETTE_MODE"] = "record" if _known.record else "replay"
if _known.record:
    # Recording is a batch job on a free tier: wait rather than fail.
    os.environ.setdefault("LLM_MAX_ATTEMPTS", "6")
    os.environ.setdefault("LLM_BACKOFF_SECONDS", "4")

sys.path.insert(0, str(HERE.parent / "backend"))
from src.services.grounding import check_grounding  # noqa: E402

DATA = HERE / "dataset.jsonl"
RESULTS = HERE / "results.json"

# Floors, not targets. Catching fabrications is the job, so recall is held
# higher than precision: a false flag is a nag, a missed fabrication is a lie
# on someone's resume.
MIN_RECALL = 0.85
MIN_PRECISION = 0.75


def score(rows):
    """Metrics for the positive class 'caught a fabrication'."""
    tp = sum(1 for r in rows if not r["expected"] and not r["predicted"])
    fp = sum(1 for r in rows if r["expected"] and not r["predicted"])
    fn = sum(1 for r in rows if not r["expected"] and r["predicted"])
    tn = sum(1 for r in rows if r["expected"] and r["predicted"])
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "n": len(rows),
        "accuracy": (tp + tn) / len(rows) if rows else 0.0,
        "precision": precision,
        "recall": recall,
        "f1": (2 * precision * recall / (precision + recall)) if precision + recall else 0.0,
        "missed_fabrications": fn,
        "false_flags": fp,
    }


async def main():
    parser = argparse.ArgumentParser(parents=[_args])
    parser.add_argument("--verbose", action="store_true", help="list every wrong row")
    parser.add_argument("--pause", type=float, default=None,
                        help="seconds between live calls (default: 2.2 live, 0 on tape)")
    parser.add_argument("--prompt-version", default=None,
                        help="which backend/prompts/grounding/*.txt to score (default: v1)")
    args = parser.parse_args()

    on_tape = args.replay
    if not on_tape and not os.getenv("GROQ_API_KEY"):
        print("Set GROQ_API_KEY, or run with --replay to use the recorded tape.")
        return 1

    pause = args.pause if args.pause is not None else (0.0 if on_tape else 2.2)
    rows = [json.loads(line) for line in DATA.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    print("{} rows ({} supported / {} fabricated) — {}".format(
        len(rows), sum(1 for r in rows if r["expected_supported"]),
        sum(1 for r in rows if not r["expected_supported"]),
        "replaying the tape" if on_tape else
        ("recording a new tape" if args.record else "calling the live API")))

    scored = []
    for index, row in enumerate(rows):
        if index and pause:
            await asyncio.sleep(pause)
        [check] = await check_grounding(row["cv"], [row["statement"]],
                                        version=args.prompt_version)
        scored.append({
            "statement": row["statement"],
            "tag": row.get("tag", "original"),
            "expected": row["expected_supported"],
            "predicted": check["supported"],
            "issue": check.get("issue"),
        })
        if not on_tape and (index + 1) % 10 == 0:
            print("  {}/{}".format(index + 1, len(rows)), flush=True)

    overall = score(scored)
    by_tag = {}
    grouped = defaultdict(list)
    for row in scored:
        grouped[row["tag"]].append(row)
    for tag, group in sorted(grouped.items()):
        by_tag[tag] = score(group)

    print("\noverall   accuracy {accuracy:.2f} | precision {precision:.2f} | "
          "recall {recall:.2f} | f1 {f1:.2f}".format(**overall))
    print("          {} fabrications missed, {} true statements wrongly flagged".format(
        overall["missed_fabrications"], overall["false_flags"]))

    print("\n{:24} {:>4} {:>6} {:>7} {:>7}".format("by kind", "n", "acc", "missed", "flagged"))
    for tag, stats in sorted(by_tag.items(), key=lambda kv: kv[1]["accuracy"]):
        print("{:24} {n:>4} {accuracy:>6.2f} {missed_fabrications:>7} {false_flags:>7}".format(
            tag, **stats))

    if args.verbose:
        print("\nrows the guardrail got wrong:")
        for row in scored:
            if row["expected"] != row["predicted"]:
                kind = "MISSED a fabrication" if not row["expected"] else "wrongly flagged"
                print("  [{}] ({}) {}".format(kind, row["tag"], row["statement"][:100]))

    results_path = RESULTS
    if args.prompt_version and args.prompt_version != "v1":
        # Keep each version's report so two can be compared side by side.
        results_path = HERE / "results_{}.json".format(args.prompt_version)
    results_path.write_text(json.dumps({
        "overall": overall, "by_tag": by_tag,
        "prompt_version": args.prompt_version or "v1",
        "source": "tape" if on_tape else "live",
        "rows": scored,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\nwrote {}".format(results_path.name))

    failed = []
    if overall["recall"] < MIN_RECALL:
        failed.append("recall {:.2f} < {}".format(overall["recall"], MIN_RECALL))
    if overall["precision"] < MIN_PRECISION:
        failed.append("precision {:.2f} < {}".format(overall["precision"], MIN_PRECISION))
    if failed:
        print("FAIL: " + "; ".join(failed))
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
