"""Attach stored embeddings to the hand-labelled items in eval/relevance_labels.csv.

Reads each labelled URL's embedding from the database (items must already be embedded with the
model in osint.embeddings) and writes eval/relevance_embeddings.npz. The labels file holds only
URL, source, label and title; article text is never copied into the repository.

    OSINT_DATABASE_URL=... python scripts/build_relevance_dataset.py
"""

import csv
from pathlib import Path

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

from osint.config import database_url

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    with open(ROOT / "eval" / "relevance_labels.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    url = database_url().replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url) as conn:
        register_vector(conn)
        found = dict(
            conn.execute(
                "SELECT url, embedding FROM raw_item WHERE url = ANY(%s) AND embedding IS NOT NULL",
                ([r["url"] for r in rows],),
            ).fetchall()
        )
    kept = [r for r in rows if r["url"] in found]
    missing = len(rows) - len(kept)
    X = np.array([found[r["url"]].to_numpy() for r in kept], dtype=np.float32)
    np.savez_compressed(
        ROOT / "eval" / "relevance_embeddings.npz", urls=np.array([r["url"] for r in kept]), X=X
    )
    print(f"{len(kept)} labelled items embedded; {missing} labelled URLs not found in the database")


if __name__ == "__main__":
    main()
