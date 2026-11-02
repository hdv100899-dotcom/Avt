"""Machine-translate headlines into Vietnamese, locally and for free.

Uses NLLB-200 (600M, int8) through CTranslate2 on the CPU. This is gist-quality translation: it
reads fine for most headlines but can mistranslate proper names and rare words, so the dashboard
always shows the original beside it and labels the translation as machine-made. The NLLB weights
are licensed CC-BY-NC 4.0 (non-commercial use only).
"""

import re
import threading
from collections.abc import Sequence
from typing import Protocol

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from osint.models import RawItem, Source

MODEL_REPO = "JustFrederik/nllb-200-distilled-600M-ct2-int8"
MODEL_NAME = "nllb-200-distilled-600M-int8"
TARGET = "vie_Latn"
NLLB_CODES = {
    "en": "eng_Latn", "ru": "rus_Cyrl", "uk": "ukr_Cyrl", "zh": "zho_Hans", "ko": "kor_Hang",
    "ja": "jpn_Jpan", "ar": "arb_Arab", "fa": "pes_Arab", "hi": "hin_Deva", "tr": "tur_Latn",
    "fr": "fra_Latn", "de": "deu_Latn", "es": "spa_Latn", "it": "ita_Latn", "pl": "pol_Latn",
    "pt": "por_Latn", "ro": "ron_Latn", "th": "tha_Thai",
}  # fmt: skip
VIETNAMESE_MARKS = re.compile(r"[ăâđêôơưĂÂĐÊÔƠƯạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]")
SENTENCE_END = re.compile(r"(?<=[.!?…])\s+(?=\S)")
QUOTES = str.maketrans({c: '"' for c in "«»“”„‟‹›「」『』"} | {c: "'" for c in "‘’‚‛"})
MAX_RATIO = 4.0  # a translation more than this many times longer than its source is a loop


class Translator(Protocol):
    model_name: str

    def translate(self, pairs: Sequence[tuple[str, str]]) -> list[str | None]:
        """Translate (text, source language) pairs to Vietnamese; None where it could not."""


def source_language(title: str, declared: str | None) -> str | None:
    """Language of a headline: what the feed declares, except where the script says otherwise
    (feeds mislabel East Asian text). None means do not translate (Vietnamese or unknown)."""
    if VIETNAMESE_MARKS.search(title):
        return None
    letters = sum(c.isalpha() for c in title) or 1
    if sum("가" <= c <= "힣" for c in title) / letters > 0.2:
        return "ko"
    if sum("぀" <= c <= "ヿ" for c in title) / letters > 0.1:
        return "ja"
    if sum("一" <= c <= "鿿" for c in title) / letters > 0.3:
        return declared if declared in ("zh", "ja") else "zh"
    return declared if declared in NLLB_CODES else None


def segments(title: str) -> list[str]:
    """Quotes normalised (the model turns « » into junk) and multi-sentence headlines split, since
    NLLB tends to translate only the first sentence of a long input."""
    text = re.sub(r"\s+", " ", title.translate(QUOTES)).strip()
    return [s for s in SENTENCE_END.split(text) if s.strip()] if len(text) > 60 else [text]


def clean_output(source: str, output: str) -> str | None:
    out = re.sub(r"\s*⁇\s*", " ", output).strip()
    if not out or len(out) > MAX_RATIO * max(len(source), 20):
        return None
    words = out.lower().split()
    if len(words) >= 8 and len(set(words)) <= len(words) / 3:
        return None  # the decoder looped
    return out


class NllbTranslator:
    model_name = MODEL_NAME

    def __init__(self, model_dir: str | None = None, threads: int = 4, beam: int = 2) -> None:
        self._model_dir = model_dir
        self._threads = threads
        self._beam = beam
        self._lock = threading.Lock()
        self._translator = None
        self._sp = None

    def _load(self) -> None:
        import ctranslate2
        import sentencepiece

        path = self._model_dir
        if path is None:
            from huggingface_hub import snapshot_download

            path = snapshot_download(MODEL_REPO)
        self._sp = sentencepiece.SentencePieceProcessor()
        self._sp.load(f"{path}/sentencepiece.bpe.model")
        self._translator = ctranslate2.Translator(
            path, device="cpu", compute_type="int8", inter_threads=1, intra_threads=self._threads
        )

    def translate(self, pairs: Sequence[tuple[str, str]]) -> list[str | None]:
        with self._lock:
            if self._translator is None:
                self._load()
            parts: list[tuple[int, str, str]] = []  # (pair index, segment, language)
            for i, (text, lang) in enumerate(pairs):
                parts += [(i, seg, lang) for seg in segments(text)]
            order = sorted(
                range(len(parts)), key=lambda k: len(parts[k][1])
            )  # similar lengths batch well
            sources = [
                [NLLB_CODES[parts[k][2]]] + self._sp.encode(parts[k][1], out_type=str) + ["</s>"]
                for k in order
            ]
            results = self._translator.translate_batch(
                sources,
                target_prefix=[[TARGET]] * len(sources),
                beam_size=self._beam,
                max_decoding_length=96,
                repetition_penalty=1.1,
                no_repeat_ngram_size=4,
                max_batch_size=32,
            )
            decoded: dict[int, str] = {}
            for k, res in zip(order, results, strict=True):
                decoded[k] = self._sp.decode(res.hypotheses[0][1:])
        joined: dict[int, list[str]] = {}
        for k, (i, _, _) in enumerate(parts):
            joined.setdefault(i, []).append(decoded[k])
        return [clean_output(pairs[i][0], " ".join(joined.get(i, []))) for i in range(len(pairs))]


def translate_pending(session: Session, translator: Translator, limit: int = 64) -> int:
    """Translate up to ``limit`` untranslated headlines, most military-relevant first.

    Returns how many items were handled (including ones deliberately left untranslated, which are
    marked so they are not picked again). Vietnamese and unknown-language titles are skipped.
    """
    rows = session.execute(
        select(RawItem.id, RawItem.title, Source.language)
        .join(Source, Source.id == RawItem.source_id)
        .where(RawItem.title.is_not(None), RawItem.title_vi_model.is_(None))
        .order_by(RawItem.relevance.desc().nulls_last(), RawItem.id)
        .limit(limit)
    ).all()
    if not rows:
        return 0
    plan = [(i, t, source_language(t, lang)) for i, t, lang in rows]
    todo = [(i, t, lang) for i, t, lang in plan if lang]
    outputs = translator.translate([(t, lang) for _, t, lang in todo]) if todo else []
    translated = {i: out for (i, _, _), out in zip(todo, outputs, strict=True)}
    for item_id, _, lang in plan:
        out = translated.get(item_id)
        session.execute(
            update(RawItem)
            .where(RawItem.id == item_id)
            # The model name marks "handled"; title_vi stays NULL where nothing was translated.
            .values(title_vi=out, title_vi_model=translator.model_name if lang else "skipped")
        )
    return len(rows)
