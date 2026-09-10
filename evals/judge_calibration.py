"""Score the guardrail against a person's labels, and the eval set against them too.

The guardrail is a model judging a model. Nothing in this repo measured whether
it is right — the eval set it is scored on was itself written by a model, so a
perfect score could mean "the judge agrees with whoever wrote the answers"
rather than "the judge is correct".

A human labelling pass fixes both problems at once, and this reports both
comparisons:

  judge vs human      is the guardrail right? Precision and recall for catching
                      fabrications, plus Cohen's kappa, which corrects for the
                      agreement you would get by chance on an unbalanced set.
  eval set vs human   is the dataset right? Rows where the two disagree are
                      rows where the eval set is teaching the wrong lesson, and
                      they should be fixed before anything is measured on them.

    python evals/judge_calibration.py --labels evals/human_labels.json

`human_labels.json` is what the label desk artifact produced:
{"ground-007": "yes", "ground-011": "no", "ground-019": "unsure", ...}
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATASET = HERE / "dataset.jsonl"
RESULTS = HERE / "results.json"
OUT = HERE / "judge_calibration.json"


def kappa(a, b):
    """Cohen's kappa between two binary labellings of the same items.

    Raw agreement flatters an unbalanced set: if 80% of rows are fabrications,
    a judge that says "fabrication" every time agrees 80% of the time and knows
    nothing. Kappa subtracts that.
    """
    n = len(a)
    if n == 0:
        return 0.0
    observed = sum(1 for x, y in zip(a, b) if x == y) / n
    pa1, pb1 = sum(a) / n, sum(b) / n
    expected = pa1 * pb1 + (1 - pa1) * (1 - pb1)
    if expected >= 1.0:
        return 1.0
    return (observed - expected) / (1 - expected)


def scores(human, other, positive_is_fabrication=True):
    """Precision/recall for the 'caught a fabrication' class."""
    tp = sum(1 for h, o in zip(human, other) if not h and not o)
    fp = sum(1 for h, o in zip(human, other) if h and not o)
    fn = sum(1 for h, o in zip(human, other) if not h and o)
    tn = sum(1 for h, o in zip(human, other) if h and o)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "n": len(human),
        "agreement": (tp + tn) / len(human) if human else 0.0,
        "kappa": kappa([int(h) for h in human], [int(o) for o in other]),
        "precision": precision, "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "missed_fabrications": fn, "false_flags": fp,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", type=Path, default=HERE / "human_labels.json")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if not args.labels.exists():
        print("No human labels at {}.\nLabel the rows in the label desk first, "
              "then export them here.".format(args.labels))
        return 1

    human_raw = json.loads(args.labels.read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines()
            if line.strip()]

    judged = {}
    if RESULTS.exists():
        for row in json.loads(RESULTS.read_text(encoding="utf-8")).get("rows", []):
            judged[row["statement"]] = row["predicted"]

    human, dataset_says, judge_says, kept = [], [], [], []
    unsure = 0
    for key, verdict in human_raw.items():
        if verdict == "unsure":
            unsure += 1
            continue
        try:
            index = int(str(key).rsplit("-", 1)[1])
        except (IndexError, ValueError):
            continue
        if index >= len(rows):
            continue
        row = rows[index]
        human.append(verdict == "yes")
        dataset_says.append(bool(row["expected_supported"]))
        judge_says.append(judged.get(row["statement"]))
        kept.append(row)

    if not human:
        print("No usable labels yet.")
        return 1

    print("{} labelled rows ({} marked unsure and excluded, never guessed)\n".format(
        len(human), unsure))

    dataset_vs_human = scores(human, dataset_says)
    print("EVAL SET vs YOU")
    print("  agreement {agreement:.2f} | kappa {kappa:.2f} | rows the set has "
          "backwards: {disputed}".format(
              disputed=sum(1 for h, d in zip(human, dataset_says) if h != d),
              **dataset_vs_human))

    have_judge = [i for i, v in enumerate(judge_says) if v is not None]
    report = {"dataset_vs_human": dataset_vs_human, "unsure": unsure}
    if have_judge:
        h = [human[i] for i in have_judge]
        j = [judge_says[i] for i in have_judge]
        judge_vs_human = scores(h, j)
        print("\nGUARDRAIL vs YOU (on the {} of those it has judged)".format(len(h)))
        print("  agreement {agreement:.2f} | kappa {kappa:.2f}".format(**judge_vs_human))
        print("  catching fabrications: precision {precision:.2f} | recall {recall:.2f}"
              .format(**judge_vs_human))
        print("  {missed_fabrications} fabrications it missed, {false_flags} true "
              "statements it wrongly flagged".format(**judge_vs_human))
        report["judge_vs_human"] = judge_vs_human
    else:
        print("\nNo guardrail verdicts to compare yet: run evals/run_evals.py first "
              "so results.json exists.")

    if args.verbose:
        print("\nrows where you and the eval set disagree:")
        for row, h, d in zip(kept, human, dataset_says):
            if h != d:
                print("  you: {:>13} | set: {:>13} | {}".format(
                    "supported" if h else "not supported",
                    "supported" if d else "not supported", row["statement"][:80]))
        if have_judge:
            print("\nrows where you and the guardrail disagree:")
            for i in have_judge:
                if human[i] != judge_says[i]:
                    print("  you: {:>13} | judge: {:>13} | {}".format(
                        "supported" if human[i] else "not supported",
                        "supported" if judge_says[i] else "not supported",
                        kept[i]["statement"][:80]))

    report["tags_labelled"] = Counter(r.get("tag", "original") for r in kept)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("\nwrote {}".format(OUT.name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
