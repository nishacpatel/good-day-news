"""Group articles that report the same event (PRD section 15).

Vectors are unit length, so cosine similarity is a dot product. Each article joins the most
similar existing group when the similarity to that group's centroid reaches the threshold;
otherwise it starts a new group.
"""

import numpy as np


def cluster(vectors: list[np.ndarray], threshold: float) -> list[list[int]]:
    """Group vector indexes. Returns groups in order of first appearance."""
    groups: list[list[int]] = []
    centroids: list[np.ndarray] = []
    for i, v in enumerate(vectors):
        if centroids:
            sims = np.array([float(np.dot(v, c)) for c in centroids])
            best = int(sims.argmax())
            if sims[best] >= threshold:
                groups[best].append(i)
                members = np.stack([vectors[j] for j in groups[best]])
                c = members.mean(axis=0)
                centroids[best] = c / np.linalg.norm(c)
                continue
        groups.append([i])
        centroids.append(v)
    return groups


def best_match(vector: np.ndarray, candidates: list[tuple[int, np.ndarray]], threshold: float) -> int | None:
    """Id of the most similar candidate at or above the threshold, else None."""
    best_id, best_sim = None, threshold
    for cid, cvec in candidates:
        sim = float(np.dot(vector, cvec))
        if sim >= best_sim:
            best_id, best_sim = cid, sim
    return best_id
