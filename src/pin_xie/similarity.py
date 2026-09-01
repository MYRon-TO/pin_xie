from __future__ import annotations

from .cluster import LCSObject
from .models import InputToken, input_token_text


def jaccard_similarity(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def jaccard_filter(
    tokens: list[InputToken], clusters: list[LCSObject]
) -> list[LCSObject]:
    if not tokens or not clusters:
        return []

    token_set = {input_token_text(token) for token in tokens}
    threshold = len(tokens) / 2

    candidates: list[LCSObject] = []
    for cluster in clusters:
        if len(cluster.token_set & token_set) > threshold:
            candidates.append(cluster)

    return candidates
