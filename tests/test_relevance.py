import csv
import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from osint.embeddings import EMBEDDING_DIM, MODEL_NAME
from osint.models import RawItem
from osint.relevance import RelevanceModel, load_model, score_items, score_pending
from osint.semantic import cluster_step
from osint.sources import add_source
from osint.web import create_app
from tests.test_dedup import add_item, article, make_source

ROOT = Path(__file__).resolve().parents[1]


def unit(*coords: float) -> list[float]:
    norm = math.sqrt(sum(c * c for c in coords))
    return [c / norm for c in coords] + [0.0] * (EMBEDDING_DIM - len(coords))


@pytest.fixture(autouse=True)
def toy_model(monkeypatch):
    """Axis 0 means "military": margin = 4 * x0 - 1, so x0 > 0.25 is relevant."""
    coef = np.zeros(EMBEDDING_DIM)
    coef[0] = 4.0
    model = RelevanceModel("toy-v1", coef, intercept=0.0, threshold=1.0, metrics={})
    monkeypatch.setattr("osint.relevance.load_model", lambda: model)
    return model


def test_margin_is_score_minus_threshold(toy_model) -> None:
    military, civilian = unit(1, 0), unit(0, 1)
    assert toy_model.margins([military, civilian]) == pytest.approx([3.0, -1.0])


def test_score_items_stores_margin_and_version(session: Session) -> None:
    s = make_source(session, 1)
    mil, _ = add_item(session, s, "a", content=article(1))
    civ, _ = add_item(session, s, "b", content=article(2))
    mil.embedding, civ.embedding = unit(1, 0), unit(0, 1)
    no_vec, _ = add_item(session, s, "c", content=article(3))
    session.flush()

    assert score_items(session, [mil.id, civ.id, no_vec.id]) == 2  # no embedding, no score
    session.refresh(mil)
    session.refresh(civ)
    session.refresh(no_vec)
    assert mil.relevance == pytest.approx(3.0) and mil.relevance_version == "toy-v1"
    assert civ.relevance == pytest.approx(-1.0)
    assert no_vec.relevance is None
    assert score_items(session, []) == 0


def test_score_pending_skips_current_and_rescore_redoes(session: Session) -> None:
    s = make_source(session, 1)
    a, _ = add_item(session, s, "a", content=article(1))
    a.embedding = unit(1, 0)
    session.flush()
    assert score_pending(session) == 1
    assert score_pending(session) == 0
    assert score_pending(session, rescore=True) == 1


def test_cluster_step_scores_what_it_embeds(factory) -> None:
    class Embedder:
        model_name = "fake"

        def embed(self, texts):
            return [unit(1, 0) if "Missile" in t else unit(0, 1) for t in texts]

    with factory() as session, session.begin():
        src = add_source(session, kind="rss", locator="https://a.example/f", name="A")
        add_item(session, src, "1", title="Missile test", content=article(1))
        add_item(session, src, "2", title="Bake sale", content=article(2))
    cluster_step(factory, Embedder())
    with factory() as session:
        margins = {r.title: r.relevance for r in session.scalars(select(RawItem))}
    assert margins["Missile test"] > 0 > margins["Bake sale"]


@pytest.fixture
def client(factory, temp_database, monkeypatch):
    from osint.dedup import group_pending

    monkeypatch.setenv("OSINT_DATABASE_URL", temp_database)
    now = datetime.now(UTC)
    with factory() as session, session.begin():
        src = add_source(session, kind="rss", locator="https://a.example/f", name="A")
        for i, (title, margin) in enumerate(
            [("Warship launched", 2.0), ("Celebrity wedding", -2.0), ("Brand new item", None)]
        ):
            session.add(
                RawItem(
                    source_id=src.id,
                    external_id=str(i),
                    title=title,
                    content=article(i),
                    published_at=now,
                    relevance=margin,
                    analysis_status="pending",
                    url=f"https://a.example/{i}",
                )
            )
        session.flush()
        group_pending(session)
    with TestClient(create_app()) as c:
        yield c


def titles(client, **params) -> set[str]:
    return {g["title"] for g in client.get("/api/groups", params=params).json()}


def test_scope_military_hides_scored_irrelevant_but_not_unscored(client) -> None:
    assert titles(client) == {"Warship launched", "Brand new item"}  # military is the default
    assert titles(client, scope="military") == {"Warship launched", "Brand new item"}


def test_scope_all_and_other(client) -> None:
    assert titles(client, scope="all") == {
        "Warship launched",
        "Celebrity wedding",
        "Brand new item",
    }
    assert titles(client, scope="other") == {"Celebrity wedding"}
    assert client.get("/api/groups", params={"scope": "bogus"}).status_code == 422


def test_group_reports_its_best_relevance(client) -> None:
    by_title = {g["title"]: g["relevance"] for g in client.get("/api/groups?scope=all").json()}
    assert by_title["Warship launched"] == pytest.approx(2.0)
    assert by_title["Brand new item"] is None


# ---- the shipped model --------------------------------------------------------------------


def test_shipped_weights_match_the_embedding_model_and_dataset() -> None:
    # `load_model` was imported before the autouse fixture patched the module attribute, so
    # this is the real loader reading the shipped weights.
    real = load_model()
    assert real.version == "relevance-v1" and len(real.coef) == EMBEDDING_DIM
    assert MODEL_NAME  # trained on this embedding model, enforced inside load_model

    data = np.load(ROOT / "eval" / "relevance_embeddings.npz")
    with open(ROOT / "eval" / "relevance_labels.csv", newline="") as f:
        labels = {r["url"]: r["label"] for r in csv.DictReader(f)}
    y = np.array([labels[u] for u in data["urls"]])
    keep = y != "b"
    margins = np.array(real.margins(data["X"][keep]))
    truth = y[keep] == "r"
    recall = (margins[truth] >= 0).mean()
    removed = (margins[~truth] < 0).mean()
    # In-sample, so a floor rather than a quality claim: the file must be consistent with the data.
    assert recall >= 0.95 and removed >= 0.9
