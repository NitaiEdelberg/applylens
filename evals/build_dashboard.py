"""Build the numbers the app shows about itself, from the eval reports.

The header badge used to read a hand-copied file from July: 33 cases, 100%.
The committed eval had since grown to 95 cases at 97.9%, with two true claims
wrongly flagged. A product whose pitch is "it never lies about your CV" was
overstating its own accuracy. Nothing was wrong with the eval; the number on
screen had simply stopped being connected to it.

So the badge and the Evals tab are generated here, from the reports the eval
scripts write, and CI runs this with --check: if a report changes and the UI
numbers do not, the build fails.

    python evals/build_dashboard.py           # regenerate
    python evals/build_dashboard.py --check   # CI: fail if the UI is stale

Inputs (all committed):
  results.json              grounding guardrail, replayed from the recorded tape
  judge_calibration.json    the guardrail and the dataset vs a person's labels
  retrieval_results.json    RAG retrieval (deterministic TF-IDF path)
  coverage_model_report.json  the trained coverage model vs the rule, held out
  skillmatch (computed)     the deterministic coverage signal, recomputed here
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BADGE = os.path.join(ROOT, "frontend", "src", "eval-results.json")
DASHBOARD = os.path.join(ROOT, "frontend", "src", "eval-dashboard.json")


def load(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return json.load(f)


def r(x, n=3):
    return round(float(x), n) if isinstance(x, (int, float)) else x


def skillmatch():
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "sm.json")
        subprocess.run([sys.executable, os.path.join(HERE, "run_skillmatch_eval.py"), "--json", out],
                       check=True, capture_output=True)
        with open(out, encoding="utf-8") as f:
            return json.load(f)


def build():
    g = load("results.json")
    o = g["overall"]
    cal = load("judge_calibration.json")
    ret = load("retrieval_results.json")
    cov = load("coverage_model_report.json")
    sm = skillmatch()

    badge = {
        "accuracy": r(o["accuracy"]), "precision": r(o["precision"]), "recall": r(o["recall"]),
        "n": o["n"], "missed_fabrications": o["missed_fabrications"], "false_flags": o["false_flags"],
        "prompt_version": g.get("prompt_version"),
    }

    by_tag = sorted(
        ({"tag": t, "n": v["n"], "accuracy": r(v["accuracy"]),
          "missed": v["missed_fabrications"], "false_flags": v["false_flags"]}
         for t, v in g["by_tag"].items()),
        key=lambda x: (-x["n"], x["tag"]))

    sections = [
        {
            "id": "grounding",
            "title": "Grounding guardrail",
            "question": "Does it catch claims your CV does not support, without flagging true ones?",
            "headline": [
                {"label": "accuracy", "value": r(o["accuracy"]), "kind": "pct"},
                {"label": "fabrications missed", "value": o["missed_fabrications"], "of": o["n"], "kind": "count", "good": "low"},
                {"label": "true claims wrongly flagged", "value": o["false_flags"], "of": o["n"], "kind": "count", "good": "low"},
                {"label": "labelled statements", "value": o["n"], "kind": "count"},
            ],
            "how": f"{o['n']} hand-labelled CV statements across {len(by_tag)} kinds of fabrication and "
                   f"look-alike truth. Prompt {g.get('prompt_version')}. CI replays the recorded model answers "
                   "on every push, so a prompt or parsing change that breaks the guardrail fails the build "
                   "without spending tokens.",
            "table": {"columns": ["kind", "n", "accuracy", "missed", "false flags"],
                      "rows": [[t["tag"], t["n"], t["accuracy"], t["missed"], t["false_flags"]] for t in by_tag]},
        },
        {
            "id": "human",
            "title": "Checked against a person",
            "question": "Are the labels themselves right, and does the guardrail agree with a human?",
            "headline": [
                {"label": "guardrail vs human agreement", "value": r(cal["judge_vs_human"]["agreement"]), "kind": "pct"},
                {"label": "Cohen's kappa", "value": r(cal["judge_vs_human"]["kappa"], 2), "kind": "num"},
                {"label": "dataset labels vs human", "value": r(cal["dataset_vs_human"]["agreement"]), "kind": "pct"},
                {"label": "statements a person labelled", "value": cal["judge_vs_human"]["n"], "kind": "count"},
            ],
            "how": "A person re-labelled a sample blind. Measuring the guardrail only against labels the same "
                   "author wrote would grade it on agreeing with its author; this measures it against someone "
                   f"checking. Where they disagree, the guardrail missed {cal['judge_vs_human']['missed_fabrications']} "
                   f"fabrications and wrongly flagged {cal['judge_vs_human']['false_flags']} true claims.",
        },
        {
            "id": "coverage",
            "title": "Skill coverage signal (no LLM)",
            "question": "Which job requirements does the CV actually cover, checked by rules instead of a model?",
            "headline": [
                {"label": "precision", "value": r(sm["systems"]["current"]["precision"]), "kind": "pct"},
                {"label": "recall", "value": r(sm["systems"]["current"]["recall"]), "kind": "pct"},
                {"label": "baseline recall (before)", "value": r(sm["systems"]["baseline"]["recall"]), "kind": "pct", "neutral": True},
                {"label": "labelled requirements", "value": sm["n"], "kind": "count"},
            ],
            "how": "A deterministic second opinion next to the model's fit score, recomputed on every CI run. "
                   "A trained classifier was also tried: on CVs it never saw it scored "
                   f"F1 {r(cov['held_out']['model']['f1'], 2)} against the rule's "
                   f"{r(cov['held_out']['rule']['f1'], 2)}, so the rule stayed. That result is kept here on purpose.",
        },
        {
            "id": "retrieval",
            "title": "Career-history retrieval (RAG)",
            "question": "When you paste a longer history, does it pull the right passages for this job?",
            "headline": [
                {"label": f"recall@{ret['k']}", "value": r(ret["recall"]), "kind": "pct"},
                {"label": "MRR", "value": r(ret["mrr"], 2), "kind": "num"},
                {"label": "cases", "value": len(ret["cases"]), "kind": "count"},
            ],
            "how": f"Measured on the deterministic {ret['embedder'].upper()} path that runs without any API key, "
                   "so CI can gate on it. A hosted embedder is used in production when a key is set.",
        },
        {
            "id": "injection",
            "title": "Prompt-injection screening",
            "question": "Does a job ad that talks to the AI get caught?",
            "headline": [
                {"label": "planted instructions caught in real job ads", "value": 1.0, "kind": "pct"},
                {"label": "clean real job ads flagged", "value": 0, "of": 45, "kind": "count", "good": "low"},
            ],
            "how": "Job descriptions are screened by JailbreakAPI as untrusted documents. Its own CI measures "
                   "1,485 planted instructions across 15 real postings and 45 clean ones.",
            "link": {"href": "https://jailbreak-api-frontend.onrender.com/redteam.html", "label": "JailbreakAPI red-team scorecard"},
        },
    ]
    return badge, {"sections": sections}


def write(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="fail if the committed UI numbers are stale")
    args = ap.parse_args()
    badge, dashboard = build()
    if args.check:
        stale = []
        for path, data in ((BADGE, badge), (DASHBOARD, dashboard)):
            try:
                with open(path, encoding="utf-8") as f:
                    if json.load(f) != data:
                        stale.append(os.path.relpath(path, ROOT))
            except FileNotFoundError:
                stale.append(os.path.relpath(path, ROOT) + " (missing)")
        if stale:
            print("STALE: the numbers the app shows no longer match the eval reports: " + ", ".join(stale))
            print("Run: python evals/build_dashboard.py")
            return 1
        print("UI numbers match the eval reports")
        return 0
    write(BADGE, badge)
    write(DASHBOARD, dashboard)
    print(f"badge: {badge['accuracy']:.1%} on {badge['n']} | wrote {os.path.relpath(DASHBOARD, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
