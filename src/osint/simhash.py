"""64-bit SimHash over word shingles, for finding near-duplicate articles.

Two texts that differ by a footer, a corrected sentence or a changed headline end up a few
bits apart; unrelated texts are about 32 bits apart.
"""

import hashlib
import re

SHINGLE = 3
# Below this many words a hash says too little; only exact matches are trusted.
MIN_WORDS = 40
MAX_DISTANCE = 3


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold())


def simhash(text: str | None) -> int | None:
    """Signed 64-bit SimHash (as stored in a bigint column), or None for short texts."""
    words = _words(text or "")
    if len(words) < MIN_WORDS:
        return None
    counts = [0] * 64
    for i in range(len(words) - SHINGLE + 1):
        shingle = " ".join(words[i : i + SHINGLE])
        h = int.from_bytes(hashlib.blake2b(shingle.encode(), digest_size=8).digest(), "big")
        for bit in range(64):
            counts[bit] += 1 if (h >> bit) & 1 else -1
    value = sum(1 << bit for bit in range(64) if counts[bit] > 0)
    return value - (1 << 64) if value >= 1 << 63 else value


def distance(a: int, b: int) -> int:
    return ((a ^ b) & ((1 << 64) - 1)).bit_count()
