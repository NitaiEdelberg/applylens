"""Train the coverage classifier, on the terms that were chosen up front.

Five decisions, made before any data existed so the result could not be chosen
to flatter a method:

  features    the rule's own signals (see services/coverage_features.py), so
              the coefficients are readable.
  grid        C x class_weight, twelve fits. Enough to find the regularisation
              strength, small enough to read every row of the table.
  validation  GroupKFold grouped by CV. Rows from one CV never straddle the
              split: without that the model sees the same career history in
              train and validation and scores several points too high.
  threshold   the highest recall available at precision >= 0.95, read off the
              precision-recall curve. A false "covered" tells someone their CV
              proves a skill it does not, and they walk into an interview on it.
  shipping    the model ships only if it beats the rule on a test set of CVs it
              never saw. If the rule wins, that is the finding.

    python evals/train_coverage_model.py
    python evals/train_coverage_model.py --test evals/coverage_test_labeled.jsonl
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.base import clone
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_recall_curve
from sklearn.model_selection import GroupKFold, GridSearchCV
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "backend"))

from src.services.coverage_features import FEATURE_NAMES, features  # noqa: E402
from src.services.skillmatch import skill_match  # noqa: E402

TRAIN = HERE / "coverage_train.jsonl"
CVS = HERE / "corpus" / "cvs.json"
MODEL_DIR = HERE.parent / "backend" / "models"
REPORT = HERE / "coverage_model_report.json"

TARGET_PRECISION = 0.95


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def build_matrix(rows, cvs):
    X, y, groups, kept = [], [], [], []
    for row in rows:
        cv_text = cvs.get(row["cv_key"])
        if not cv_text:
            continue
        X.append(features(row["requirement"], cv_text))
        y.append(1 if row.get("label", row.get("verdict") == "covered") else 0)
        groups.append(row["cv_key"])
        kept.append(row)
    return np.array(X, dtype=float), np.array(y), np.array(groups), kept


def metrics(y_true, y_pred):
    tp = int(((y_pred == 1) & (y_true == 1)).sum())
    fp = int(((y_pred == 1) & (y_true == 0)).sum())
    fn = int(((y_pred == 0) & (y_true == 1)).sum())
    tn = int(((y_pred == 0) & (y_true == 0)).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "precision": precision, "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "accuracy": (tp + tn) / len(y_true) if len(y_true) else 0.0,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
    }


def pick_threshold(y_true, scores, target=TARGET_PRECISION):
    """Highest recall at or above the target precision; else the best F1 point."""
    precision, recall, thresholds = precision_recall_curve(y_true, scores)
    best = None
    for p, r, t in zip(precision[:-1], recall[:-1], thresholds):
        if p >= target and (best is None or r > best[1]):
            best = (p, r, t)
    if best:
        return float(best[2]), {"precision": float(best[0]), "recall": float(best[1]),
                                "rule": "highest recall at precision >= {}".format(target)}
    f1 = [(2 * p * r / (p + r) if p + r else 0.0, p, r, t)
          for p, r, t in zip(precision[:-1], recall[:-1], thresholds)]
    best_f1 = max(f1) if f1 else (0, 0, 0, 0.5)
    return float(best_f1[3]), {
        "precision": float(best_f1[1]), "recall": float(best_f1[2]),
        "rule": "target precision unreachable on this data; fell back to best F1",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", type=Path, default=HERE / "coverage_test_labeled.jsonl",
                        help="hand-labelled held-out rows (produced by the label desk)")
    parser.add_argument("--folds", type=int, default=5)
    args = parser.parse_args()

    if not TRAIN.exists():
        print("No training data yet. Run evals/build_coverage_dataset.py first.")
        return 1

    cvs = json.loads(CVS.read_text(encoding="utf-8"))
    rows = read_jsonl(TRAIN)
    X, y, groups, _ = build_matrix(rows, cvs)
    n_groups = len(set(groups))
    print("{} rows over {} CVs | {} covered / {} missing".format(
        len(y), n_groups, int(y.sum()), int((1 - y).sum())))
    if len(y) < 50 or n_groups < 3:
        print("Not enough data to train honestly. Let the builder finish.")
        return 1

    folds = min(args.folds, n_groups)
    grid = GridSearchCV(
        Pipeline([("scale", StandardScaler()),
                  ("lr", LogisticRegression(max_iter=2000, solver="liblinear"))]),
        {"lr__C": [0.01, 0.1, 1, 10, 100], "lr__class_weight": [None, "balanced"]},
        # Average precision, not accuracy: the operating point is chosen off the
        # precision-recall curve, so the search should optimise that curve.
        scoring="average_precision",
        cv=GroupKFold(n_splits=folds),
        n_jobs=1,
    )
    grid.fit(X, y, groups=groups)
    print("\nbest: C={lr__C} class_weight={lr__class_weight} "
          "(mean average precision {:.3f} over {} folds)".format(
              grid.best_score_, folds, **grid.best_params_))

    print("\n{:22} {:>8}".format("grid", "avg prec"))
    for params, score in sorted(zip(grid.cv_results_["params"],
                                    grid.cv_results_["mean_test_score"]),
                                key=lambda kv: -kv[1]):
        print("{:22} {:>8.3f}".format(
            "C={} {}".format(params["lr__C"], params["lr__class_weight"] or "none"), score))

    # Out-of-fold scores, so the threshold is not chosen on rows the model fit.
    oof = np.zeros(len(y))
    for train_idx, test_idx in GroupKFold(n_splits=folds).split(X, y, groups):
        # clone(), not a fresh construction: a Pipeline cannot be rebuilt from
        # its own get_params, and re-fitting the fitted estimator would leak
        # the folds into each other.
        model = clone(grid.best_estimator_)
        model.fit(X[train_idx], y[train_idx])
        oof[test_idx] = model.predict_proba(X[test_idx])[:, 1]

    threshold, operating = pick_threshold(y, oof)
    cv_metrics = metrics(y, (oof >= threshold).astype(int))
    rule_metrics = metrics(y, X[:, FEATURE_NAMES.index("rule_says_covered")].astype(int))

    print("\nout-of-fold, at threshold {:.3f} ({})".format(threshold, operating["rule"]))
    print("{:10} {:>10} {:>8} {:>7} {:>7}".format("system", "precision", "recall", "f1", "acc"))
    for name, m in (("rule", rule_metrics), ("model", cv_metrics)):
        print("{:10} {precision:>10.3f} {recall:>8.3f} {f1:>7.3f} {accuracy:>7.3f}".format(name, **m))

    model = grid.best_estimator_
    weights = model.named_steps["lr"].coef_[0]
    print("\nwhat the model learned (standardised coefficients):")
    for name, weight in sorted(zip(FEATURE_NAMES, weights), key=lambda kv: -abs(kv[1])):
        print("  {:20} {:+.2f}".format(name, weight))

    report = {
        "n_rows": len(y), "n_cvs": n_groups, "folds": folds,
        "best_params": grid.best_params_,
        "mean_average_precision": float(grid.best_score_),
        "threshold": threshold, "operating_point": operating,
        "out_of_fold": {"rule": rule_metrics, "model": cv_metrics},
        "coefficients": dict(zip(FEATURE_NAMES, [float(w) for w in weights])),
        "label_sources": Counter(r.get("jd_source", "?") for r in rows),
    }

    # ---- the decision: does it beat the rule on hand-labelled, unseen CVs? ----
    if args.test.exists():
        test_rows = [r for r in read_jsonl(args.test) if r.get("human_label") in (True, False)]
        if test_rows:
            Xt, yt, _, _ = build_matrix(
                [dict(r, label=r["human_label"]) for r in test_rows], cvs)
            model_pred = (model.predict_proba(Xt)[:, 1] >= threshold).astype(int)
            rule_pred = np.array([1 if skill_match([r["requirement"]], cvs[r["cv_key"]])["covered"]
                                  else 0 for r in test_rows])
            test_model, test_rule = metrics(yt, model_pred), metrics(yt, rule_pred)
            print("\nHELD-OUT, hand-labelled ({} rows, CVs the model never saw)".format(len(yt)))
            print("{:10} {:>10} {:>8} {:>7}".format("system", "precision", "recall", "f1"))
            for name, m in (("rule", test_rule), ("model", test_model)):
                print("{:10} {precision:>10.3f} {recall:>8.3f} {f1:>7.3f}".format(name, **m))
            wins = test_model["f1"] > test_rule["f1"] and test_model["precision"] >= test_rule["precision"] - 0.02
            verdict = ("Ship the model: it beats the rule on unseen CVs."
                       if wins else
                       "Keep the rule. The model does not beat it on unseen CVs, and a "
                       "hundred lines of linguistics beating a classifier is a real result.")
            print("\n" + verdict)
            report["held_out"] = {"rule": test_rule, "model": test_model, "verdict": verdict}
    else:
        print("\nNo hand-labelled test set yet, so nothing here decides anything. "
              "Label the held-out rows first: the numbers above are measured against "
              "the annotator's labels, and a model that imitates the annotator would "
              "score well on them while being no better.")
        report["held_out"] = None

    MODEL_DIR.mkdir(exist_ok=True)
    try:
        import joblib
        joblib.dump({"model": model, "threshold": threshold, "features": FEATURE_NAMES},
                    MODEL_DIR / "coverage_lr.joblib")
        print("\nsaved backend/models/coverage_lr.joblib")
    except ImportError:
        print("\njoblib not installed; the model was not saved")

    REPORT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("wrote {}".format(REPORT.name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
