"""Promote reviewed feedback rows into the eval set.

The flywheel's second half. The app records verdicts people disputed; this
turns the ones that survive review into labelled eval rows. Two rules make it
safe to run:

  nothing is automatic   every row is shown and taken or dropped by hand. A
                         training set fed by unreviewed clicks learns whatever
                         annoys people, which is not the same as what is true.
  the human wins         a promoted row is labelled with what the person said,
                         because they are the one who has read the CV.

    python evals/promote_feedback.py --list
    python evals/promote_feedback.py --promote 3 7 11
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "backend"))

from src.db_sql import GuardrailFeedback, SessionLocal  # noqa: E402

DATASET = HERE / "dataset.jsonl"


def rows(session, include_promoted=False):
    query = session.query(GuardrailFeedback)
    if not include_promoted:
        query = query.filter(GuardrailFeedback.promoted == 0)
    return query.order_by(GuardrailFeedback.created_at.desc()).all()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--promote", nargs="*", type=int, default=None,
                        help="row ids to add to the eval set")
    parser.add_argument("--all", action="store_true", help="include already promoted rows")
    args = parser.parse_args()

    with SessionLocal() as session:
        pending = rows(session, args.all)

        if args.promote is None or args.list:
            if not pending:
                print("No feedback waiting. That is normal early: it needs users.")
                return 0
            print("{} rows waiting review\n".format(len(pending)))
            for row in pending:
                print("[{}] guardrail said {} · person said {}".format(
                    row.id,
                    "supported" if row.model_supported else "NOT supported",
                    "supported" if row.human_supported else "NOT supported"))
                print("     {}".format(row.statement[:110]))
                if row.issue:
                    print("     its reason: {}".format(row.issue[:100]))
                print("     cv: {}...\n".format((row.cv_excerpt or "")[:110].replace("\n", " ")))
            print("Promote with: python evals/promote_feedback.py --promote "
                  + " ".join(str(r.id) for r in pending[:3]))
            return 0

        wanted = set(args.promote)
        picked = [r for r in pending if r.id in wanted]
        if not picked:
            print("None of those ids are waiting.")
            return 1

        with DATASET.open("a", encoding="utf-8") as handle:
            for row in picked:
                handle.write(json.dumps({
                    "cv": row.cv_excerpt,
                    "statement": row.statement,
                    # The person read the CV; the model did not.
                    "expected_supported": bool(row.human_supported),
                    "tag": "from_use",
                }, ensure_ascii=False) + "\n")
                row.promoted = 1
        session.commit()

    print("Promoted {} rows into {}.".format(len(picked), DATASET.name))
    print("Re-record the tape so the replayed evals cover them:")
    print("  GROQ_API_KEY=... python evals/run_evals.py --record")
    return 0


if __name__ == "__main__":
    sys.exit(main())
