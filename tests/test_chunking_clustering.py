import numpy as np

from gooddaynews.process.chunking import chunk_text, estimate_tokens
from gooddaynews.process.clustering import best_match, cluster
from tests.conftest import topic_vector


def paragraph(words: int, word: str = "progress") -> str:
    return " ".join([word] * (words - 1)) + "."


def test_chunks_stay_within_max_size():
    text = "\n\n".join(paragraph(120) for _ in range(20))
    chunks = chunk_text(text, target_tokens=400, max_tokens=500)
    assert len(chunks) > 1
    assert all(estimate_tokens(c) <= 500 for c in chunks)
    assert all(estimate_tokens(c) >= 100 for c in chunks)


def test_long_paragraph_is_split_at_sentences():
    sentence = "Researchers measured a large improvement in the region. "
    text = sentence * 200
    chunks = chunk_text(text, target_tokens=400, max_tokens=500)
    assert len(chunks) > 1
    assert all(c.rstrip().endswith(".") for c in chunks)
    assert all(estimate_tokens(c) <= 500 for c in chunks)


def test_small_tail_is_folded_into_previous_chunk():
    text = "\n\n".join([paragraph(280), paragraph(10, "end")])
    chunks = chunk_text(text, target_tokens=300, max_tokens=500)
    assert len(chunks) == 1 and chunks[0].endswith("end.")


def test_empty_text_gives_no_chunks():
    assert chunk_text("") == []


def test_cluster_groups_same_event_and_separates_others():
    vectors = [topic_vector(t) for t in ["Solar co-op A", "Whale recovery", "solar co-op B", "Library opens"]]
    groups = cluster(vectors, threshold=0.86)
    assert sorted(map(sorted, groups)) == [[0, 2], [1], [3]]


def test_best_match_respects_threshold():
    v = topic_vector("solar story")
    candidates = [(10, topic_vector("whale story")), (11, topic_vector("solar report"))]
    assert best_match(v, candidates, 0.86) == 11
    assert best_match(topic_vector("library"), candidates, 0.86) is None


def test_cluster_handles_empty_input():
    assert cluster([], 0.86) == []
    assert best_match(np.ones(3) / np.sqrt(3), [], 0.5) is None
