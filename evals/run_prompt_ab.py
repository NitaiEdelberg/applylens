"""Score two versions of the tailoring prompt against the same jobs and CVs.

"This prompt feels better" is not a reason to ship a prompt. This runs both
versions over the same cases and reports the numbers that matter for this
product:

  grounded    share of generated bullets the guardrail says the CV supports.
              The headline: a prompt that writes beautiful unsupported bullets
              is a worse prompt.
  bullets     how many it wrote. A version that scores well by writing two
              bullets is not obviously better than one that writes five.
  supported   grounded bullets per case, which is what the candidate actually
              gets to paste into a resume.

The verdict is deliberately not automatic. Two versions within noise of each
other on twelve cases is a tie, and the script says so rather than crowning a
winner by the third decimal place.

    python evals/run_prompt_ab.py --a v1 --b v2
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "backend"))

os.environ.setdefault("LLM_MAX_ATTEMPTS", "6")
os.environ.setdefault("LLM_BACKOFF_SECONDS", "4")

from src.services.tailor import tailor  # noqa: E402

CASES_PATH = HERE / "prompt_ab_cases.json"
RESULTS = HERE / "prompt_ab_results.json"


def load_cases():
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


async def run_version(version, cases, pause):
    per_case = []
    for index, case in enumerate(cases):
        if index and pause:
            await asyncio.sleep(pause)
        result = await tailor(case["jd"], case["cv"], version=version)
        bullets = result.get("bullets", [])
        grounding = result.get("grounding", [])
        supported = sum(1 for g in grounding if g.get("supported"))
        per_case.append({
            "case": case["name"],
            "bullets": len(bullets),
            "supported": supported,
            "flagged": len(grounding) - supported,
            "cover_flagged": result.get("cover_flagged_count", 0),
        })
        print("  {:<22} {:>2} bullets, {:>2} grounded".format(
            case["name"], len(bullets), supported), flush=True)

    total_bullets = sum(c["bullets"] for c in per_case)
    total_supported = sum(c["supported"] for c in per_case)
    return {
        "version": version,
        "cases": per_case,
        "bullets": total_bullets,
        "supported": total_supported,
        "grounded_rate": (total_supported / total_bullets) if total_bullets else 0.0,
        "bullets_per_case": total_bullets / len(per_case) if per_case else 0.0,
        "supported_per_case": total_supported / len(per_case) if per_case else 0.0,
    }


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--a", default="v1")
    parser.add_argument("--b", default="v2")
    parser.add_argument("--pause", type=float, default=6.0,
                        help="seconds between cases; the free tier meters tokens per minute")
    args = parser.parse_args()

    if not os.getenv("GROQ_API_KEY"):
        print("Set GROQ_API_KEY: an A/B over prompts needs real generations.")
        return 1

    cases = load_cases()
    print("{} cases, two prompt versions\n".format(len(cases)))

    runs = {}
    for version in (args.a, args.b):
        print("{}:".format(version))
        runs[version] = await run_version(version, cases, args.pause)
        print()

    print("{:8} {:>8} {:>10} {:>9} {:>12}".format(
        "version", "bullets", "grounded", "rate", "per case"))
    for version, run in runs.items():
        print("{:8} {:>8} {:>10} {:>8.0%} {:>12.1f}".format(
            version, run["bullets"], run["supported"], run["grounded_rate"],
            run["supported_per_case"]))

    a, b = runs[args.a], runs[args.b]
    gap = b["grounded_rate"] - a["grounded_rate"]
    # Twelve cases is a small sample; a couple of points either way is noise,
    # and calling that a winner is how prompt "improvements" get shipped.
    if abs(gap) < 0.05:
        verdict = ("Too close to call on {} cases: {:+.0%} grounded rate. "
                   "Keep {}.".format(len(cases), gap, args.a))
    elif gap > 0:
        verdict = "{} wins: {:+.0%} grounded rate over {}.".format(args.b, gap, args.a)
    else:
        verdict = "{} wins: {:+.0%} grounded rate over {}.".format(args.a, -gap, args.b)
    print("\n" + verdict)

    RESULTS.write_text(json.dumps({"runs": runs, "verdict": verdict}, indent=2,
                                  ensure_ascii=False), encoding="utf-8")
    print("wrote {}".format(RESULTS.name))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
