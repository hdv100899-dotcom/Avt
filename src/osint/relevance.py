"""Is this report about military or defence matters? A small classifier over the embeddings.

Logistic regression on the sentence embeddings that grouping already computes, so scoring costs
one dot product and no model call. Trained by scripts/train_relevance.py from hand labels in
eval/; no LLM involved.

``RawItem.relevance`` stores the margin: the model's score minus the decision threshold, which is
set to keep 95% of relevant items in cross-validation. Margin >= 0 means relevant. Items nobody has
scored yet (NULL) are shown rather than hidden.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

import numpy as np
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from osint.embeddings import MODEL_NAME
from osint.models import RawItem


@dataclass(frozen=True)
class RelevanceModel:
    version: str
    coef: np.ndarray
    intercept: float
    threshold: float
    metrics: dict

    def margins(self, vectors: Sequence[Sequence[float]]) -> list[float]:
        scores = np.asarray(vectors, dtype=np.float64) @ self.coef + self.intercept
        return [float(s) for s in scores - self.threshold]


@lru_cache
def load_model() -> RelevanceModel:
    raw = json.loads(resources.files("osint.data").joinpath("relevance_v1.json").read_text())
    if raw["embedding_model"] != MODEL_NAME:
        raise RuntimeError(
            f"relevance model was trained on {raw['embedding_model']}, items use {MODEL_NAME}; "
            "retrain with scripts/train_relevance.py"
        )
    return RelevanceModel(
        version=raw["version"],
        coef=np.array(raw["coef"]),
        intercept=raw["intercept"],
        threshold=raw["threshold"],
        metrics=raw["metrics"],
    )


def score_items(session: Session, item_ids: Sequence[int]) -> int:
    """Score the given items that have an embedding; return how many were scored."""
    if not item_ids:
        return 0
    model = load_model()
    rows = session.execute(
        select(RawItem.id, RawItem.embedding).where(
            RawItem.id.in_(item_ids), RawItem.embedding.is_not(None)
        )
    ).all()
    if not rows:
        return 0
    margins = model.margins([r[1] for r in rows])
    for (item_id, _), margin in zip(rows, margins, strict=True):
        session.execute(
            update(RawItem)
            .where(RawItem.id == item_id)
            .values(relevance=margin, relevance_version=model.version)
        )
    return len(rows)


def score_pending(session: Session, rescore: bool = False, batch: int = 500) -> int:
    """Score embedded items that have no current score (every embedded item when ``rescore``)."""
    model = load_model()
    stmt = select(RawItem.id).where(RawItem.embedding.is_not(None)).order_by(RawItem.id)
    if not rescore:
        stmt = stmt.where(
            (RawItem.relevance.is_(None)) | (RawItem.relevance_version != model.version)
        )
    ids = list(session.scalars(stmt))
    return sum(score_items(session, ids[i : i + batch]) for i in range(0, len(ids), batch))
