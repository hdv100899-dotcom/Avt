"""Train the relevance filter (logistic regression on sentence embeddings).

Reads eval/relevance_labels.csv and eval/relevance_embeddings.npz, reports cross-validated
quality (folds grouped by source, so a feed's own articles never sit in both train and test),
then fits on everything and writes src/osint/data/relevance_v1.json.

Labels: r = military/defence relevant, n = not, b = borderline (kept out of training and metrics).
The decision threshold is the value that keeps 95% of relevant items in cross-validation, because
dropping a relevant report costs more than showing an irrelevant one.
"""

import csv
import json
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_recall_curve, roc_auc_score
from sklearn.model_selection import GroupKFold

from osint.embeddings import MODEL_NAME

ROOT = Path(__file__).resolve().parents[1]
TARGET_RECALL = 0.95
C = 3.0
VERSION = "relevance-v1"


def make_model() -> LogisticRegression:
    return LogisticRegression(C=C, max_iter=5000, class_weight="balanced")


def main() -> None:
    with open(ROOT / "eval" / "relevance_labels.csv", newline="") as f:
        labels = {r["url"]: r for r in csv.DictReader(f)}
    data = np.load(ROOT / "eval" / "relevance_embeddings.npz")
    rows = [labels[u] for u in data["urls"]]
    keep = [i for i, r in enumerate(rows) if r["label"] in ("r", "n")]
    X = data["X"][keep]
    y = np.array([1 if rows[i]["label"] == "r" else 0 for i in keep])
    groups = [rows[i]["source"] for i in keep]
    print(
        f"{len(y)} labelled items ({y.sum()} relevant, {(1 - y).sum()} not); "
        f"{sum(r['label'] == 'b' for r in rows)} borderline held out"
    )

    scores = np.zeros(len(y))
    for train, test in GroupKFold(n_splits=5).split(X, y, groups):
        scores[test] = make_model().fit(X[train], y[train]).decision_function(X[test])
    precision, recall, thresholds = precision_recall_curve(y, scores)
    ok = [
        (p, t)
        for p, r, t in zip(precision[:-1], recall[:-1], thresholds, strict=True)
        if r >= TARGET_RECALL
    ]
    cv_precision, threshold = max(ok, key=lambda pt: pt[1])
    removed = float(((scores < threshold) & (y == 0)).sum() / (y == 0).sum())
    auc = float(roc_auc_score(y, scores))
    print(
        f"grouped CV: AUROC {auc:.3f}; at recall >= {TARGET_RECALL}: precision {cv_precision:.3f}, "
        f"irrelevant removed {removed:.0%}"
    )

    model = make_model().fit(X, y)
    borderline = [i for i, r in enumerate(rows) if r["label"] == "b"]
    if borderline:
        share = float((model.decision_function(data["X"][borderline]) >= threshold).mean())
        print(f"borderline items scored relevant: {share:.0%}")

    out = {
        "version": VERSION,
        "embedding_model": MODEL_NAME,
        "coef": [round(float(w), 6) for w in model.coef_[0]],
        "intercept": round(float(model.intercept_[0]), 6),
        "threshold": round(float(threshold), 6),
        "metrics": {
            "labelled": int(len(y)),
            "relevant": int(y.sum()),
            "cv_auroc": round(auc, 4),
            "cv_precision_at_recall": round(float(cv_precision), 4),
            "target_recall": TARGET_RECALL,
            "cv_irrelevant_removed": round(removed, 4),
            "cv": "5-fold, grouped by source",
        },
    }
    (ROOT / "src" / "osint" / "data" / "relevance_v1.json").write_text(json.dumps(out) + "\n")
    print("wrote src/osint/data/relevance_v1.json")


if __name__ == "__main__":
    main()
