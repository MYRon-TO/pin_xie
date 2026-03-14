from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .cluster import LCSObject, create_cluster
from .lcs import lcs
from .similarity import jaccard_filter
from .template import TemplateToken, extract_parameters, merge_template
from .tokenizer import LogTokenizer
from .trie import PrefixTree, trie_match


@dataclass
class ParseResult:
    cluster_id: int
    template_tokens: list[TemplateToken]
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
        self.header_config_state: dict[str, Any] | None = None

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

    def to_template_state(
        self,
        *,
        header_config: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if header_config is not None:
            self.header_config_state = self._normalize_header_config(header_config)

        state: dict[str, Any] = {
            "version": 1,
            "tau_ratio": self.tau_ratio,
            "next_cluster_id": self.next_cluster_id,
            "clusters": [
                {
                    "cluster_id": cluster.cluster_id,
                    "template_tokens": list(cluster.template_tokens),
                    "variable_names": dict(cluster.variable_names),
                }
                for cluster in self.all_clusters()
            ],
        }

        if self.header_config_state is not None:
            state["header"] = self._normalize_header_config(self.header_config_state)

        return state

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

        raw_header_config = state.get("header")
        if raw_header_config is not None:
            if not isinstance(raw_header_config, Mapping):
                raise ValueError("Invalid template cache: header must be an object")
            parser.header_config_state = cls._normalize_header_config(raw_header_config)

        for item in raw_clusters:
            if not isinstance(item, Mapping):
                raise ValueError(
                    "Invalid template cache: cluster item must be an object"
                )

            raw_cluster_id = item.get("cluster_id")
            raw_template_tokens = item.get("template_tokens", [])
            raw_variable_names = item.get("variable_names", {})

            if not isinstance(raw_cluster_id, int):
                raise ValueError("Invalid template cache: cluster_id must be an int")
            if not isinstance(raw_template_tokens, list) or not all(
                token is None or isinstance(token, str) for token in raw_template_tokens
            ):
                raise ValueError(
                    "Invalid template cache: template_tokens must be list[str | null]"
                )
            if not isinstance(raw_variable_names, Mapping):
                raise ValueError(
                    "Invalid template cache: variable_names must be an object"
                )

            variable_names: dict[int, str] = {}
            used_names: set[str] = set()
            for raw_key, raw_name in raw_variable_names.items():
                try:
                    var_index = int(raw_key)
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        "Invalid template cache: variable name index must be int"
                    ) from exc

                if var_index < 0:
                    raise ValueError(
                        "Invalid template cache: variable name index must be >= 0"
                    )
                if not isinstance(raw_name, str):
                    raise ValueError(
                        "Invalid template cache: variable name must be str"
                    )
                name = raw_name.strip()
                if not name:
                    continue
                if name in used_names:
                    raise ValueError(
                        "Invalid template cache: duplicate variable names are not allowed"
                    )
                used_names.add(name)
                variable_names[var_index] = name

            cluster = LCSObject(
                cluster_id=raw_cluster_id,
                template_tokens=list(raw_template_tokens),
                line_ids=[],
                size=0,
                variable_names=variable_names,
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

    @staticmethod
    def _normalize_header_config(
        header_config: Mapping[str, Any],
    ) -> dict[str, Any]:
        parse_structure = str(header_config.get("parse_structure", "")).strip()
        if not parse_structure:
            raise ValueError("Invalid header config: parse_structure must be non-empty")

        raw_field_patterns = header_config.get("field_patterns", {})
        if not isinstance(raw_field_patterns, Mapping):
            raise ValueError("Invalid header config: field_patterns must be an object")

        field_patterns = {
            str(key): str(value)
            for key, value in raw_field_patterns.items()
            if value is not None and str(value).strip()
        }

        return {
            "parse_structure": parse_structure,
            "strict_mode": bool(header_config.get("strict_mode", False)),
            "field_patterns": field_patterns,
        }
