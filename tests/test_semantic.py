import math
import os
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from osint.dedup import group_item
from osint.embeddings import EMBEDDING_DIM, FastEmbedder, embedding_text
from osint.models import EventGroup, Evidence, RawItem
from osint.semantic import (
    MIN_BEST,
    MIN_MEAN,
    cluster_step,
    embed_pending,
    reconsider_singletons,
    semantic_group_item,
)
from tests.test_dedup import NOW, add_item, article, evidence, make_source


def unit(*coords: float) -> list[float]:
    """A unit vector with the given leading coordinates, so cosines are set by hand."""
    norm = math.sqrt(sum(c * c for c in coords))
    return [c / norm for c in coords] + [0.0] * (EMBEDDING_DIM - len(coords))


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def embedded(session: Session, source, ext: str, vector, seed: int, **kwargs):
    item, gid = add_item(session, source, ext, content=article(seed), **kwargs)
    item.embedding = vector
    session.flush()
    return item, gid


class FakeEmbedder:
    model_name = "fake-model"

    def __init__(self, by_title: dict[str, list[float]] | None = None) -> None:
        self.by_title = by_title or {}
        self.calls: list[list[str]] = []

    def embed(self, texts):
        self.calls.append(list(texts))
        return [self.by_title.get(t.split(".")[0], unit(1.0)) for t in texts]


def test_thresholds_are_sane() -> None:
    assert 0 < MIN_MEAN <= MIN_BEST < 1


def test_same_event_from_another_source_joins_with_reason_and_score(session: Session) -> None:
    a, b = make_source(session, 1), make_source(session, 2)
    base = unit(1, 0)
    close = unit(0.85, math.sqrt(1 - 0.85**2))
    _, g1 = embedded(session, a, "a", base, 1, url="https://a.example/1")
    item, g2 = embedded(session, b, "b", close, 2, url="https://b.example/2")
    assert g1 != g2

    assert semantic_group_item(session, item.id) == g1
    rows = session.execute(
        select(Evidence.raw_item_id, Evidence.match_reason, Evidence.match_score).where(
            Evidence.event_group_id == g1
        )
    ).all()
    by_item = {r[0]: r for r in rows}
    assert by_item[item.id][1] == "semantic"
    assert by_item[item.id][2] == pytest.approx(0.85, abs=1e-6)
    assert (
        session.scalar(select(func.count()).select_from(EventGroup).where(EventGroup.id == g2)) == 0
    )


def test_similar_topic_below_threshold_stays_separate(session: Session) -> None:
    a, b = make_source(session, 1), make_source(session, 2)
    _, g1 = embedded(session, a, "a", unit(1, 0), 1)
    item, g2 = embedded(session, b, "b", unit(0.70, math.sqrt(1 - 0.70**2)), 2)
    assert semantic_group_item(session, item.id) is None
    assert group_item(session, item.id) == g2 != g1


def test_never_joins_a_group_holding_its_own_source(session: Session) -> None:
    a = make_source(session, 1)
    _, g1 = embedded(session, a, "weekly-1", unit(1, 0), 1)
    item, g2 = embedded(session, a, "weekly-2", unit(1, 0), 2)  # near-identical vector
    assert semantic_group_item(session, item.id) is None
    assert g1 != g2


def test_time_window(session: Session) -> None:
    a, b, c = (make_source(session, n) for n in (1, 2, 3))
    first_vec = unit(1, 0)
    _, g1 = embedded(session, a, "a", first_vec, 1, published=NOW)
    far, g_far = embedded(session, b, "b", first_vec, 2, published=NOW - timedelta(days=10))
    near, _ = embedded(session, c, "c", first_vec, 3, published=NOW - timedelta(days=1))
    assert semantic_group_item(session, far.id) is None
    assert semantic_group_item(session, near.id) == g1


def test_group_average_stops_a_story_chaining_through_one_close_pair(session: Session) -> None:
    a, b, c, d = (make_source(session, n) for n in (1, 2, 3, 4))
    va, vb = unit(1, 0, 0), unit(0.6, 0.8, 0)
    # A and B are one group (same wording), though their embeddings differ.
    ia, g = embedded(session, a, "a", va, 1)
    ib = add_item(session, b, "b", content=article(1))[0]
    ib.embedding = vb
    session.flush()
    assert group_item(session, ib.id) == g

    loose = unit(0.8, -0.6, 0)  # close to A (0.8) but orthogonal to B: mean 0.4
    tight = unit(0.95, 0.5, 0)  # close to both: mean ~0.9
    assert cosine(va, loose) == pytest.approx(0.8) and cosine(vb, loose) == pytest.approx(0.0)
    ic, _ = embedded(session, c, "c", loose, 3)
    id_, _ = embedded(session, d, "d", tight, 4)

    assert semantic_group_item(session, ic.id) is None
    assert semantic_group_item(session, id_.id) == g


def test_item_in_a_shared_group_is_left_alone(session: Session) -> None:
    a, b, c = (make_source(session, n) for n in (1, 2, 3))
    embedded(session, a, "a", unit(1, 0), 1)
    dup, g_dup = embedded(session, b, "b", unit(0, 1), 1)  # same wording as the first: one group
    other, g_other = embedded(session, c, "c", unit(0, 1), 9)
    assert semantic_group_item(session, dup.id) is None
    assert evidence(session, g_dup) != evidence(session, g_other)


def test_earlier_publication_becomes_origin_after_semantic_join(session: Session) -> None:
    a, b = make_source(session, 1), make_source(session, 2)
    late, g = embedded(session, a, "late", unit(1, 0), 1, published=NOW)
    early, _ = embedded(session, b, "early", unit(1, 0), 2, published=NOW - timedelta(hours=6))
    assert semantic_group_item(session, early.id) == g
    assert [e[0] for e in evidence(session, g) if e[1]] == [early.id]
    assert late.id in [e[0] for e in evidence(session, g)]


def test_embed_pending_stores_vectors_once(session: Session) -> None:
    s = make_source(session, 1)
    one, _ = add_item(session, s, "a", title="First", content=article(1))
    two, _ = add_item(session, s, "b", title="Second", content=article(2))
    blank = RawItem(source_id=s.id, external_id="blank", analysis_status="pending")
    session.add(blank)
    session.flush()
    embedder = FakeEmbedder({"First": unit(1, 0), "Second": unit(0, 1)})

    assert embed_pending(session, embedder, limit=1) == [one.id]
    assert embed_pending(session, embedder) == [two.id]  # blank item has nothing to embed
    assert embed_pending(session, embedder) == []

    session.refresh(one)
    assert one.embedding_model == "fake-model"
    assert list(one.embedding)[:2] == pytest.approx([1.0, 0.0])
    assert embedder.calls[0][0].startswith("First. ")


def test_embedding_text_uses_title_and_lede_only() -> None:
    text = embedding_text("Title", "x" * 5000)
    assert text.startswith("Title. ") and len(text) < 700
    assert embedding_text(None, None) == "."


def test_cluster_step_end_to_end(factory) -> None:
    from osint.sources import add_source

    with factory() as session, session.begin():
        a = add_source(session, kind="rss", locator="https://a.example/f", name="A")
        b = add_source(session, kind="rss", locator="https://b.example/f", name="B")
        for source, ext, title, seed in [
            (a, "1", "Event one", 1),
            (b, "2", "Event one again", 2),
            (b, "3", "Other thing", 3),
        ]:
            add_item(session, source, ext, title=title, content=article(seed))
    embedder = FakeEmbedder(
        {
            "Event one": unit(1, 0),
            "Event one again": unit(0.9, math.sqrt(1 - 0.81)),
            "Other thing": unit(0, 0, 1),
        }
    )

    assert cluster_step(factory, embedder) == (3, 1)
    assert cluster_step(factory, embedder) == (0, 0)  # nothing left to do
    with factory() as session:
        sizes = sorted(
            session.scalars(
                select(func.count()).select_from(Evidence).group_by(Evidence.event_group_id)
            )
        )
    assert sizes == [1, 2]


@pytest.mark.skipif(
    not os.environ.get("OSINT_TEST_REAL_MODEL"),
    reason="downloads a 220 MB model; set OSINT_TEST_REAL_MODEL=1",
)
def test_real_model_ranks_same_event_above_same_topic() -> None:
    embedder = FastEmbedder()
    texts = [
        "Marine Corps creates first medium missile battalion. The service redesignated a "
        "battalion in Hawaii as its first Medium Range Missile unit armed with anti-ship missiles.",
        "U.S. Marine Corps stands up first NMESIS anti-ship missile unit. A Marine battalion in "
        "Hawaii was redesignated as the first Medium Range Missile battalion.",
        "Army re-evaluating munitions procurement goals. Officials said production targets for "
        "artillery shells will be reviewed after new estimates of wartime consumption.",
        "Marine Corps recruits begin training. The new class of recruits arrived at Parris Island.",
    ]
    v = embedder.embed(texts)
    assert len(v[0]) == EMBEDDING_DIM
    assert cosine(v[0], v[0]) == pytest.approx(1.0, abs=1e-5)  # normalised
    same_event, unrelated_topic, same_org = (
        cosine(v[0], v[1]),
        cosine(v[0], v[2]),
        cosine(v[0], v[3]),
    )
    assert same_event >= MIN_BEST
    assert same_event > unrelated_topic + 0.2 and same_event > same_org + 0.2


def test_reconsider_joins_lone_items_that_now_qualify(session: Session) -> None:
    a, b, c = (make_source(session, n) for n in (1, 2, 3))
    a_item, g1 = embedded(session, a, "a", unit(1, 0), 1)
    # B arrived while it looked unrelated; its embedding has since been refreshed.
    b_item, g2 = embedded(session, b, "b", unit(0, 1), 2)
    other, g3 = embedded(session, c, "c", unit(0, 0, 1), 3)
    assert reconsider_singletons(session) == 0

    b_item.embedding = unit(0.9, math.sqrt(1 - 0.81))
    session.flush()
    assert reconsider_singletons(session) == 1
    group_of = {
        raw_id: gid
        for raw_id, gid in session.execute(select(Evidence.raw_item_id, Evidence.event_group_id))
    }
    assert group_of[a_item.id] == group_of[b_item.id]
    assert group_of[other.id] == g3 and g3 != group_of[a_item.id]
    assert reconsider_singletons(session) == 0  # nothing left to join
