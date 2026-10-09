"""List the most similar article pairs, for labelling duplicate detection (eval/dedupe_labels.yaml).

    python -m gooddaynews.evaluation.dedupe_pairs           # prints candidate pairs with similarity
"""

import itertools
import sys

import numpy as np

from gooddaynews.db import connect
from gooddaynews.llm import GeminiLLM
from gooddaynews.process.models import ArticleRecord

MIN_SIMILARITY = 0.78


def article_vectors(conn, llm) -> list[tuple[int, str, str, np.ndarray]]:
    """(article id, source, title, vector) using the same lead text the pipeline clusters on."""
    rows = conn.run("""select a.id, s.name, a.title, coalesce(a.feed_summary, ''), coalesce(a.body, '')
                       from articles a join sources s on s.id = a.source_id
                       where a.status in ('processed', 'rejected') and a.story_id is not null
                       order by a.id""")
    leads = [ArticleRecord(url="", title=r[2], feed_summary=r[3], body=r[4], published_at=None, source_name=r[1],
                           source_domain="", source_country="", credibility=3, is_primary=False).lead() for r in rows]
    vectors = llm.embed(leads)
    return [(r[0], r[1], r[2], v) for r, v in zip(rows, vectors)]


def candidate_pairs(items, min_similarity: float = MIN_SIMILARITY):
    pairs = []
    for (a, sa, ta, va), (b, sb, tb, vb) in itertools.combinations(items, 2):
        sim = float(np.dot(va, vb))
        if sim >= min_similarity:
            pairs.append((round(sim, 3), a, sa, ta, b, sb, tb))
    return sorted(pairs, reverse=True)


def main() -> int:
    conn = connect()
    try:
        items = article_vectors(conn, GeminiLLM())
    finally:
        conn.close()
    for sim, a, sa, ta, b, sb, tb in candidate_pairs(items):
        print(f"- [{a}, {b}, {sim}]  # {sa}: {ta[:60]} || {sb}: {tb[:60]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
