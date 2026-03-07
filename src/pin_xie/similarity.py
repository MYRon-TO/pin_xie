from __future__ import annotations

from .cluster import LCSObject


def jaccard_similarity(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def jaccard_filter(tokens: list[str], clusters: list[LCSObject]) -> list[LCSObject]:
    if not tokens or not clusters:
        return []

    token_set = set(tokens)
    threshold = len(tokens) / 2

    candidates: list[LCSObject] = []
    for cluster in clusters:
        if len(cluster.token_set & token_set) > threshold:
            candidates.append(cluster)

    return candidates
