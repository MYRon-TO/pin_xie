from __future__ import annotations

import math
from dataclasses import dataclass, field

from .cluster import LCSObject


@dataclass(eq=False)
class TrieNode:
    children: dict[str, "TrieNode"] = field(default_factory=dict)
    terminal_cluster_ids: set[int] = field(default_factory=set)


class PrefixTree:
    def __init__(self) -> None:
        self.root = TrieNode()

    def clear(self) -> None:
        self.root = TrieNode()

    def build(self, clusters: list[LCSObject]) -> None:
        self.clear()
        for cluster in clusters:
            self.insert(cluster)

    def insert(self, cluster: LCSObject) -> None:
        constant_tokens = [token for token in cluster.template_tokens if token != "*"]
        if not constant_tokens:
            return

        node = self.root
        for token in constant_tokens:
            child = node.children.get(token)
            if child is None:
                child = TrieNode()
                node.children[token] = child
            node = child

        node.terminal_cluster_ids.add(cluster.cluster_id)

    def match(
        self,
        tokens: list[str],
        clusters_by_id: dict[int, LCSObject],
        min_match_ratio: float = 0.5,
    ) -> int | None:
        if not tokens:
            return None

        states: set[TrieNode] = {self.root}
        for token in tokens:
            next_states = set(states)
            for state in states:
                child = state.children.get(token)
                if child is not None:
                    next_states.add(child)
            states = next_states

        candidate_ids: set[int] = set()
        for state in states:
            candidate_ids.update(state.terminal_cluster_ids)

        if not candidate_ids:
            return None

        min_constants = max(1, math.ceil(len(tokens) * min_match_ratio))
        best_cluster_id: int | None = None
        best_constant_count = -1
        best_template_len = math.inf

        for cluster_id in candidate_ids:
            cluster = clusters_by_id.get(cluster_id)
            if cluster is None:
                continue

            constant_count = cluster.constant_token_count
            if constant_count < min_constants:
                continue

            template_len = len(cluster.template_tokens)
            if constant_count > best_constant_count or (
                constant_count == best_constant_count
                and template_len < best_template_len
            ):
                best_cluster_id = cluster_id
                best_constant_count = constant_count
                best_template_len = template_len

        return best_cluster_id


def trie_match(
    tokens: list[str],
    trie: PrefixTree,
    clusters_by_id: dict[int, LCSObject],
    min_match_ratio: float = 0.5,
) -> int | None:
    return trie.match(
        tokens, clusters_by_id=clusters_by_id, min_match_ratio=min_match_ratio
    )
