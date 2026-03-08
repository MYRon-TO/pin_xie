from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .cluster import LCSObject, create_cluster
from .lcs import lcs
from .similarity import jaccard_filter
from .template import extract_parameters, merge_template
from .tokenizer import LogTokenizer
from .trie import PrefixTree, trie_match


@dataclass
class ParseResult:
    cluster_id: int
    template_tokens: list[str]
    parameters: list[str]
    tokens: list[str]


def select_best_cluster(
    tokens: list[str], candidates: list[LCSObject], tau: int
) -> int | None:
    best_cluster: LCSObject | None = None
    best_lcs_len = -1

    for cluster in candidates:
        lcs_len, _ = lcs(cluster.template_tokens, tokens)
        if lcs_len > best_lcs_len:
            best_cluster = cluster
            best_lcs_len = lcs_len
            continue

        if lcs_len == best_lcs_len and best_cluster is not None:
            if len(cluster.template_tokens) < len(best_cluster.template_tokens):
                best_cluster = cluster

    if best_cluster is None or best_lcs_len < tau:
        return None

    return best_cluster.cluster_id


class SpellParser:
    def __init__(
        self, tau_ratio: float = 0.5, tokenizer: LogTokenizer | None = None
    ) -> None:
        self.tau_ratio = tau_ratio
        self.tokenizer = tokenizer or LogTokenizer()

        self.clusters_by_id: dict[int, LCSObject] = {}
        self.cluster_order: list[int] = []
        self.trie = PrefixTree()
        self.next_cluster_id = 0
        self.next_line_id = 0

    def process(
        self,
        log: str,
        line_id: int | None = None,
        *,
        update_model: bool = True,
    ) -> ParseResult:
        if line_id is None:
            line_id = self.next_line_id
            self.next_line_id += 1

        tokens = self.tokenizer.tokenize(log)
        tau = self._tau(len(tokens))

        # 1) Prefix tree fast path
        cluster_id = trie_match(
            tokens,
            trie=self.trie,
            clusters_by_id=self.clusters_by_id,
            min_match_ratio=self.tau_ratio,
        )
        if cluster_id is not None:
            cluster = self.clusters_by_id[cluster_id]
            lcs_len, _ = lcs(cluster.template_tokens, tokens)
            if lcs_len >= tau:
                params = extract_parameters(tokens, cluster.template_tokens)
                if update_model:
                    cluster.add_line(line_id)
                return ParseResult(
                    cluster_id, list(cluster.template_tokens), params, tokens
                )

        # 2) Jaccard candidate filter
        all_clusters = [
            self.clusters_by_id[cluster_id] for cluster_id in self.cluster_order
        ]
        candidates = jaccard_filter(tokens, all_clusters)

        # 3) Select best cluster by LCS
        best_cluster_id = select_best_cluster(tokens, candidates, tau=tau)

        # 4) Merge or create
        if best_cluster_id is not None:
            cluster = self.clusters_by_id[best_cluster_id]
            _, best_lcs_tokens = lcs(cluster.template_tokens, tokens)

            if update_model:
                new_template = merge_template(
                    cluster.template_tokens, tokens, best_lcs_tokens
                )
                cluster.update_template(new_template)
                cluster.add_line(line_id)

                self._rebuild_trie()
                params = extract_parameters(tokens, new_template)
                return ParseResult(
                    cluster.cluster_id, list(new_template), params, tokens
                )

            params = extract_parameters(tokens, cluster.template_tokens)
            return ParseResult(
                cluster.cluster_id, list(cluster.template_tokens), params, tokens
            )

        if not update_model:
            return ParseResult(-1, [], [], tokens)

        cluster = self._create_new_cluster(tokens, line_id)
        self.trie.insert(cluster)
        return ParseResult(
            cluster.cluster_id, list(cluster.template_tokens), [], tokens
        )

    def parse(
        self,
        log: str,
        line_id: int | None = None,
        *,
        update_model: bool = True,
    ) -> ParseResult:
        return self.process(log, line_id=line_id, update_model=update_model)

    def all_clusters(self) -> list[LCSObject]:
        return [self.clusters_by_id[cluster_id] for cluster_id in self.cluster_order]

    def _create_new_cluster(self, tokens: list[str], line_id: int) -> LCSObject:
        cluster = create_cluster(self.next_cluster_id, tokens, line_id)
        self.clusters_by_id[cluster.cluster_id] = cluster
        self.cluster_order.append(cluster.cluster_id)
        self.next_cluster_id += 1
        return cluster

    def _rebuild_trie(self) -> None:
        clusters = [
            self.clusters_by_id[cluster_id] for cluster_id in self.cluster_order
        ]
        self.trie.build(clusters)

    def _tau(self, token_count: int) -> int:
        if token_count <= 0:
            return 0
        return max(1, int(token_count * self.tau_ratio))

    def to_template_state(self) -> dict[str, Any]:
        return {
            "version": 1,
            "tau_ratio": self.tau_ratio,
            "next_cluster_id": self.next_cluster_id,
            "clusters": [
                {
                    "cluster_id": cluster.cluster_id,
                    "template_tokens": list(cluster.template_tokens),
                }
                for cluster in self.all_clusters()
            ],
        }

    @classmethod
    def from_template_state(
        cls,
        state: Mapping[str, Any],
        *,
        tokenizer: LogTokenizer | None = None,
        tau_ratio: float | None = None,
    ) -> "SpellParser":
        raw_tau_ratio = state.get("tau_ratio", 0.5)
        effective_tau_ratio = (
            float(raw_tau_ratio) if tau_ratio is None else float(tau_ratio)
        )

        parser = cls(tau_ratio=effective_tau_ratio, tokenizer=tokenizer)

        raw_clusters = state.get("clusters", [])
        if not isinstance(raw_clusters, list):
            raise ValueError("Invalid template cache: clusters must be a list")

        for item in raw_clusters:
            if not isinstance(item, Mapping):
                raise ValueError(
                    "Invalid template cache: cluster item must be an object"
                )

            raw_cluster_id = item.get("cluster_id")
            raw_template_tokens = item.get("template_tokens", [])

            if not isinstance(raw_cluster_id, int):
                raise ValueError("Invalid template cache: cluster_id must be an int")
            if not isinstance(raw_template_tokens, list) or not all(
                isinstance(token, str) for token in raw_template_tokens
            ):
                raise ValueError(
                    "Invalid template cache: template_tokens must be list[str]"
                )

            cluster = LCSObject(
                cluster_id=raw_cluster_id,
                template_tokens=list(raw_template_tokens),
                line_ids=[],
                size=0,
            )
            parser.clusters_by_id[cluster.cluster_id] = cluster
            parser.cluster_order.append(cluster.cluster_id)

        raw_next_cluster_id = state.get("next_cluster_id")
        if isinstance(raw_next_cluster_id, int):
            parser.next_cluster_id = raw_next_cluster_id
        elif parser.cluster_order:
            parser.next_cluster_id = max(parser.cluster_order) + 1

        parser._rebuild_trie()
        return parser
