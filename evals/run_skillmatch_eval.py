"""Score the deterministic skill-coverage signal against human labels.

Two systems are compared on the same labelled cases:

  baseline  the original signal: a requirement counts as covered when at least
            half of its raw tokens appear verbatim in the CV.
  current   what src/services/skillmatch.py does today.

Why both: "the new one gets 0.9" means nothing without the number it replaced,
and a rule change that raises recall by wrecking precision is a regression that
a single accuracy figure would hide.

Run:  python evals/run_skillmatch_eval.py [--verbose]
Exit code is non-zero when `current` scores below the floors at the bottom, so
CI fails on a regression instead of printing one.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sklearn.feature_extraction.text import TfidfVectorizer  # noqa: E402

from src.services.skillmatch import skill_match  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
_ANALYZE = TfidfVectorizer(stop_words="english").build_analyzer()

# Floors, not targets: raise them when a change genuinely beats them.
MIN_PRECISION = 0.85
MIN_RECALL = 0.85


def baseline_covered(requirement: str, cv_text: str, threshold: float = 0.5) -> bool:
    """The original rule, kept here so the comparison stays honest."""
    cv_tokens = set(_ANALYZE(cv_text))
    terms = set(_ANALYZE(requirement))
    if not terms:
        return requirement.lower() in cv_text.lower()
    return sum(1 for t in terms if t in cv_tokens) / len(terms) >= threshold


def current_covered(requirement: str, cv_text: str) -> bool:
    return bool(skill_match([requirement], cv_text)["covered"])


def score(predictions, labels):
    tp = sum(1 for p, y in zip(predictions, labels) if p and y)
    fp = sum(1 for p, y in zip(predictions, labels) if p and not y)
    fn = sum(1 for p, y in zip(predictions, labels) if not p and y)
    tn = sum(1 for p, y in zip(predictions, labels) if not p and not y)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "precision": precision, "recall": recall, "f1": f1,
        "accuracy": (tp + tn) / len(labels) if labels else 0.0,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true", help="list every wrong case")
    args = ap.parse_args()

    cvs = json.load(open(os.path.join(HERE, "skillmatch_cvs.json"), encoding="utf-8"))
    cases = [json.loads(line) for line in
             open(os.path.join(HERE, "skillmatch_cases.jsonl"), encoding="utf-8")
             if line.strip()]

    labels = [c["covered"] for c in cases]
    runs = {
        "baseline": [baseline_covered(c["requirement"], cvs[c["cv_key"]]) for c in cases],
        "current": [current_covered(c["requirement"], cvs[c["cv_key"]]) for c in cases],
    }

    print(f"{len(cases)} labelled cases "
          f"({sum(labels)} covered / {len(labels) - sum(labels)} missing)\n")
    print(f"{'system':10} {'precision':>10} {'recall':>8} {'f1':>7} {'acc':>7}   "
          f"{'fp':>3} {'fn':>3}")
    results = {}
    for name, preds in runs.items():
        s = results[name] = score(preds, labels)
        print(f"{name:10} {s['precision']:>10.2f} {s['recall']:>8.2f} {s['f1']:>7.2f} "
              f"{s['accuracy']:>7.2f}   {s['fp']:>3} {s['fn']:>3}")

    if args.verbose:
        print("\nCases `current` gets wrong:")
        for c, pred in zip(cases, runs["current"]):
            if pred != c["covered"]:
                kind = "false positive" if pred else "false negative"
                print(f"  [{kind}] {c['cv_key']}: {c['requirement']!r}  ({c['why']})")

    cur = results["current"]
    failed = []
    if cur["precision"] < MIN_PRECISION:
        failed.append(f"precision {cur['precision']:.2f} < {MIN_PRECISION}")
    if cur["recall"] < MIN_RECALL:
        failed.append(f"recall {cur['recall']:.2f} < {MIN_RECALL}")
    if failed:
        print("\nFAIL: " + "; ".join(failed))
        return 1
    print("\nPASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
