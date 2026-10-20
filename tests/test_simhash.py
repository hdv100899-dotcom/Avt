import random

from osint.simhash import MAX_DISTANCE, MIN_WORDS, distance, simhash

VOCAB = [f"word{i}" for i in range(400)]


def article(seed: int, words: int = 150) -> str:
    rng = random.Random(seed)
    return " ".join(rng.choice(VOCAB) for _ in range(words))


def test_identical_text_has_identical_hash() -> None:
    assert simhash(article(1)) == simhash(article(1))


def test_stable_across_calls_and_in_bigint_range() -> None:
    h = simhash(article(2))
    assert -(1 << 63) <= h < (1 << 63)
    assert h == simhash(article(2))


def test_case_and_punctuation_do_not_matter() -> None:
    text = article(3)
    shouty = text.upper().replace(" ", ", ", 5)
    assert distance(simhash(text), simhash(shouty)) == 0


def test_small_additions_stay_within_threshold() -> None:
    text = article(4)
    footer = text + " subscribe to our newsletter for daily updates"
    byline = "WASHINGTON (Reuters) - " + text
    assert distance(simhash(text), simhash(footer)) <= MAX_DISTANCE
    assert distance(simhash(text), simhash(byline)) <= MAX_DISTANCE


def test_unrelated_texts_are_far_apart() -> None:
    distances = [distance(simhash(article(a)), simhash(article(a + 1000))) for a in range(20)]
    assert min(distances) > 15


def test_short_text_has_no_hash() -> None:
    assert simhash(" ".join(["word"] * (MIN_WORDS - 1))) is None
    assert simhash("") is None and simhash(None) is None


def test_distance_handles_negative_signed_values() -> None:
    assert distance(-1, 0) == 64
    assert distance(-1, -1) == 0
    assert distance(-(1 << 63), (1 << 63) - 1) == 64
