"""Measure retrieval on its own, before the model gets a chance to hide it.

RAG has two halves and only one of them was ever measured here. If retrieval
hands the tailoring step the wrong four paragraphs, the bullets are grounded in
the wrong experience and every downstream number still looks fine — the
guardrail happily confirms that a bullet about the wrong job is supported by the
retrieved text about the wrong job.

So: label which paragraphs of a career history SHOULD surface for a given job,
then ask the retriever and count.

  recall@k     of the paragraphs that should have surfaced, how many did. The
               one that matters: a missed paragraph is experience the candidate
               silently does not get credit for.
  precision@k  how much of what came back belonged there. Lower is tolerable —
               an extra paragraph costs tokens, not correctness.
  MRR          how high the first right answer landed.

Runs offline by default: with no embeddings key the retriever falls back to
scikit-learn TF-IDF, which is deterministic, needs no network, and is what CI
uses. Pass --with-key to measure the hosted embedder instead and compare.

    python evals/run_retrieval_eval.py
"""
import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "backend"))

CASES = HERE / "retrieval_cases.json"
RESULTS = HERE / "retrieval_results.json"

# Floors for the offline TF-IDF path, which is what CI runs.
MIN_RECALL_AT_4 = 0.80


def load_cases():
    return json.loads(CASES.read_text(encoding="utf-8"))


def evaluate(case, k, retrieve):
    career_text = "\n\n".join(case["chunks"])
    result = retrieve(case["query"], career_text, k)
    got = result["chunks"]

    # Match on the chunk's leading sentence: the retriever returns the text, and
    # comparing whole paragraphs is brittle to whitespace normalisation.
    def ident(text):
        return text.strip()[:60]

    relevant = {ident(case["chunks"][i]) for i in case["relevant"]}
    retrieved = [ident(c) for c in got]
    hits = [c for c in retrieved if c in relevant]

    rank = next((i + 1 for i, c in enumerate(retrieved) if c in relevant), 0)
    return {
        "name": case["name"],
        "recall": len(set(hits)) / len(relevant) if relevant else 0.0,
        "precision": len(hits) / len(retrieved) if retrieved else 0.0,
        "reciprocal_rank": 1.0 / rank if rank else 0.0,
        "missed": [case["chunks"][i][:60] for i in case["relevant"]
                   if ident(case["chunks"][i]) not in retrieved],
        "source": result.get("source", "?"),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-k", type=int, default=4, help="chunks retrieved per query")
    parser.add_argument("--with-key", action="store_true",
                        help="use the hosted embedder instead of the TF-IDF fallback")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if not args.with_key:
        # Force the deterministic path, whatever is in the environment.
        os.environ.pop("JINA_API_KEY", None)
        os.environ.pop("GEMINI_API_KEY", None)

    from src.services.rag import retrieve_context  # noqa: E402 — after the env is set

    cases = load_cases()
    scored = [evaluate(case, args.k, retrieve_context) for case in cases]

    recall = sum(s["recall"] for s in scored) / len(scored)
    precision = sum(s["precision"] for s in scored) / len(scored)
    mrr = sum(s["reciprocal_rank"] for s in scored) / len(scored)
    source = scored[0]["source"] if scored else "?"

    print("{} cases, k={}, embedder: {}\n".format(len(cases), args.k, source))
    print("{:26} {:>8} {:>10} {:>6}".format("case", "recall", "precision", "1/rank"))
    for row in sorted(scored, key=lambda r: r["recall"]):
        print("{:26} {:>8.2f} {:>10.2f} {:>6.2f}".format(
            row["name"], row["recall"], row["precision"], row["reciprocal_rank"]))
    print("\nrecall@{} {:.2f} | precision@{} {:.2f} | MRR {:.2f}".format(
        args.k, recall, args.k, precision, mrr))

    if args.verbose:
        for row in scored:
            for missed in row["missed"]:
                print("  [missed] {}: {}...".format(row["name"], missed))

    RESULTS.write_text(json.dumps({
        "k": args.k, "embedder": source,
        "recall": recall, "precision": precision, "mrr": mrr, "cases": scored,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    if not args.with_key and recall < MIN_RECALL_AT_4:
        print("\nFAIL: recall {:.2f} < {}".format(recall, MIN_RECALL_AT_4))
        return 1
    print("\nPASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
