import os

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from osint.models import RawItem
from osint.sources import add_source
from osint.translate import (
    VIETNAMESE_MARKS,
    NllbTranslator,
    clean_output,
    segments,
    source_language,
    translate_pending,
)
from tests.test_dedup import add_item, article


class FakeTranslator:
    model_name = "fake-mt"

    def __init__(self, fail_on: str | None = None) -> None:
        self.calls: list[list[tuple[str, str]]] = []
        self.fail_on = fail_on

    def translate(self, pairs):
        self.calls.append(list(pairs))
        return [
            None if self.fail_on and self.fail_on in t else f"VI[{lang}]: {t}" for t, lang in pairs
        ]


def test_vietnamese_and_unknown_titles_are_not_translated() -> None:
    assert source_language("Iran nã tên lửa vào tàu sân bay Mỹ", "vi") is None
    assert source_language("Quan he Viet Nam", "vi") is None  # unaccented but declared Vietnamese
    assert source_language("A headline in some language", "xx") is None
    assert source_language("Navy commissions a new patrol vessel", "en") == "en"


def test_the_script_overrides_a_wrong_feed_label() -> None:
    assert (
        source_language("忠清北道警察庁、ISIS加入図った20代男を逮捕", "ko") == "ja"
    )  # kana: Japanese
    assert source_language("한국 정부는 새로운 방위 계획을 발표했다", "en") == "ko"
    assert source_language("国防部：中国军队坚决反对美国", "en") == "zh"
    assert (
        source_language("国防部：中国军队坚决反对美国", "ja") == "ja"
    )  # kanji-only, feed says Japanese


def test_quotes_are_normalised_and_long_headlines_split_into_sentences() -> None:
    assert segments("« Comme un jour de fête » : les habitants") == [
        '" Comme un jour de fête " : les habitants'
    ]
    long = "Wleciały do Polski z terytorium Białorusi. Samoloty z Rosji w przestrzeni powietrznej"
    assert segments(long) == [
        "Wleciały do Polski z terytorium Białorusi.",
        "Samoloty z Rosji w przestrzeni powietrznej",
    ]
    assert segments("Short. Headline.") == ["Short. Headline."]  # short ones stay whole
    assert segments("  spaced   out  ") == ["spaced out"]


def test_unusable_output_is_rejected() -> None:
    assert clean_output("Navy ship", "Tàu hải quân") == "Tàu hải quân"
    assert clean_output("Navy ship", "") is None
    assert clean_output("Navy ship", "Tàu " * 100) is None  # far longer than the source
    assert clean_output("A reasonably long source headline here", "cờ " * 12) is None  # looping
    assert clean_output("x", "Giống ⁇ như một ngày lễ") == "Giống như một ngày lễ"


def test_translate_pending_stores_skips_and_does_not_repeat(session: Session) -> None:
    en = add_source(session, kind="rss", locator="https://a.example/f", name="A", language="en")
    vi = add_source(session, kind="rss", locator="https://b.example/f", name="B", language="vi")
    english, _ = add_item(
        session, en, "1", title="Navy commissions patrol vessel", content=article(1)
    )
    viet, _ = add_item(session, vi, "2", title="Hải quân thông báo tàu mới", content=article(2))
    bad, _ = add_item(session, en, "3", title="Untranslatable headline BAD", content=article(3))
    translator = FakeTranslator(fail_on="BAD")

    assert translate_pending(session, translator) == 3
    for item in (english, viet, bad):
        session.refresh(item)
    assert english.title_vi == "VI[en]: Navy commissions patrol vessel"
    assert english.title_vi_model == "fake-mt"
    assert viet.title_vi is None and viet.title_vi_model == "skipped"  # already Vietnamese
    assert bad.title_vi is None and bad.title_vi_model == "fake-mt"  # rejected, but not retried
    assert [t for t, _ in translator.calls[0]] == [
        "Navy commissions patrol vessel",
        "Untranslatable headline BAD",
    ]

    assert translate_pending(session, translator) == 0  # everything is marked handled


def test_most_relevant_headlines_go_first_and_limit_applies(session: Session) -> None:
    src = add_source(session, kind="rss", locator="https://a.example/f", name="A", language="en")
    low, _ = add_item(session, src, "low", title="Celebrity wedding", content=article(1))
    high, _ = add_item(session, src, "high", title="Warship launched", content=article(2))
    low.relevance, high.relevance = -3.0, 4.0
    session.flush()
    translator = FakeTranslator()

    assert translate_pending(session, translator, limit=1) == 1
    first = [t for t, _ in translator.calls[0]]
    assert first == ["Warship launched"]
    rows = {r.title: r.title_vi_model for r in session.scalars(select(RawItem))}
    assert rows["Warship launched"] == "fake-mt" and rows["Celebrity wedding"] is None


@pytest.mark.skipif(
    not os.environ.get("OSINT_TEST_REAL_MODEL"),
    reason="downloads a 620 MB model; set OSINT_TEST_REAL_MODEL=1",
)
def test_real_model_translates_to_vietnamese() -> None:
    out = NllbTranslator(threads=2).translate(
        [
            ("The ministry said the new frigate will enter service next year.", "en"),
            ("Россия заявила о завершении учений на южном направлении", "ru"),
        ]
    )
    assert all(out)
    assert all(VIETNAMESE_MARKS.search(o) for o in out)  # Vietnamese, not an echo of the source
