# ruff: noqa: TRY004 - malformed public cache data is reported as ValueError
# pyright: reportUnknownArgumentType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar, final

from .cluster import LCSObject, create_cluster
from .lcs import lcs
from .models import (
    InputToken,
    LiteralTemplateToken,
    ParameterCapture,
    PlainTokenSource,
    RegexTokenSource,
    TemplateToken,
    TokenSource,
    VariableTemplateToken,
    normalize_sources,
    template_token_to_json,
)
from .similarity import jaccard_filter
from .template import extract_parameters, merge_template
from .tokenizer import LogTokenizer
from .trie import PrefixTree, trie_match


@dataclass
class ParseResult:
    cluster_id: int
    template_tokens: list[TemplateToken]
    parameters: list[ParameterCapture]
    tokens: list[InputToken]


def select_best_cluster(
    tokens: list[InputToken], candidates: list[LCSObject], tau: int
) -> int | None:
    best_cluster: LCSObject | None = None
    best_lcs_len = -1
    for cluster in candidates:
        lcs_len, _ = lcs(cluster.template_tokens, tokens)
        if lcs_len > best_lcs_len:
            best_cluster, best_lcs_len = cluster, lcs_len
            continue
        if (
            lcs_len == best_lcs_len
            and best_cluster is not None
            and len(cluster.template_tokens) < len(best_cluster.template_tokens)
        ):
            best_cluster = cluster
    if best_cluster is None or best_lcs_len < tau:
        return None
    return best_cluster.cluster_id


@final
class SpellParser:
    _ROOT_FIELDS: ClassVar[set[str]] = {
        "version",
        "input",
        "header",
        "learning",
        "tokenizer",
        "tau_ratio",
        "next_cluster_id",
        "clusters",
    }

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
        self, log: str, line_id: int | None = None, *, update_model: bool = True
    ) -> ParseResult:
        if line_id is None:
            line_id = self.next_line_id
            self.next_line_id += 1
        tokens = self.tokenizer.tokenize(log)
        tau = self._tau(len(tokens))
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

        all_clusters = [self.clusters_by_id[item] for item in self.cluster_order]
        candidates = jaccard_filter(tokens, all_clusters)
        best_cluster_id = select_best_cluster(tokens, candidates, tau=tau)
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
                return ParseResult(
                    cluster.cluster_id,
                    list(new_template),
                    extract_parameters(tokens, new_template),
                    tokens,
                )
            return ParseResult(
                cluster.cluster_id,
                list(cluster.template_tokens),
                extract_parameters(tokens, cluster.template_tokens),
                tokens,
            )
        if not update_model:
            return ParseResult(-1, [], [], tokens)
        cluster = self._create_new_cluster(tokens, line_id)
        self.trie.insert(cluster)
        return ParseResult(
            cluster.cluster_id, list(cluster.template_tokens), [], tokens
        )

    def parse(
        self, log: str, line_id: int | None = None, *, update_model: bool = True
    ) -> ParseResult:
        return self.process(log, line_id=line_id, update_model=update_model)

    def all_clusters(self) -> list[LCSObject]:
        return [self.clusters_by_id[item] for item in self.cluster_order]

    def _create_new_cluster(self, tokens: list[InputToken], line_id: int) -> LCSObject:
        cluster = create_cluster(self.next_cluster_id, tokens, line_id)
        self.clusters_by_id[cluster.cluster_id] = cluster
        self.cluster_order.append(cluster.cluster_id)
        self.next_cluster_id += 1
        return cluster

    def _rebuild_trie(self) -> None:
        self.trie.build(self.all_clusters())

    def _tau(self, token_count: int) -> int:
        return 0 if token_count <= 0 else max(1, int(token_count * self.tau_ratio))

    def to_template_state(
        self,
        *,
        input_config: Mapping[str, object],
        header_config: Mapping[str, object],
        learning_config: Mapping[str, object],
        tokenizer_config: Mapping[str, object],
    ) -> dict[str, object]:
        return {
            "version": 4,
            "input": self._normalize_input_config(input_config),
            "header": self._normalize_header_config(header_config),
            "learning": self._normalize_learning_config(learning_config),
            "tokenizer": self._normalize_tokenizer_config(tokenizer_config),
            "tau_ratio": self.tau_ratio,
            "next_cluster_id": self.next_cluster_id,
            "clusters": [
                {
                    "cluster_id": cluster.cluster_id,
                    "template_tokens": [
                        template_token_to_json(t) for t in cluster.template_tokens
                    ],
                }
                for cluster in self.all_clusters()
            ],
        }

    @classmethod
    def from_template_state(
        cls,
        state: Mapping[str, object],
        *,
        tokenizer: LogTokenizer | None = None,
        tau_ratio: float | None = None,
        input_config: Mapping[str, object] | None = None,
        header_config: Mapping[str, object] | None = None,
        tokenizer_config: Mapping[str, object] | None = None,
    ) -> SpellParser:
        cls._validate_template_cache_config(
            state,
            input_config=input_config,
            header_config=header_config,
            tokenizer_config=tokenizer_config,
        )
        raw_tau = state["tau_ratio"]
        if not isinstance(raw_tau, (int, float)) or isinstance(raw_tau, bool):
            raise ValueError("Invalid template cache: tau_ratio must be a number")
        parser = cls(
            tau_ratio=float(raw_tau) if tau_ratio is None else float(tau_ratio),
            tokenizer=tokenizer,
        )
        raw_clusters = state["clusters"]
        if not isinstance(raw_clusters, list):
            raise ValueError("Invalid template cache: clusters must be a list")
        seen_ids: set[int] = set()
        for item in raw_clusters:
            if not isinstance(item, Mapping) or set(item) != {
                "cluster_id",
                "template_tokens",
            }:
                raise ValueError("Invalid template cache: cluster fields are invalid")
            cluster_id = item["cluster_id"]
            if (
                not isinstance(cluster_id, int)
                or isinstance(cluster_id, bool)
                or cluster_id < 0
            ):
                raise ValueError("Invalid template cache: cluster_id must be an int")
            if cluster_id in seen_ids:
                raise ValueError("Invalid template cache: duplicate cluster_id")
            seen_ids.add(cluster_id)
            raw_tokens = item["template_tokens"]
            if not isinstance(raw_tokens, list):
                raise ValueError(
                    "Invalid template cache: template_tokens must be a list"
                )
            tokens = [cls._template_token_from_json(token) for token in raw_tokens]
            cluster = LCSObject(cluster_id=cluster_id, template_tokens=tokens)
            parser.clusters_by_id[cluster_id] = cluster
            parser.cluster_order.append(cluster_id)
        next_id = state["next_cluster_id"]
        if not isinstance(next_id, int) or isinstance(next_id, bool) or next_id < 0:
            raise ValueError("Invalid template cache: next_cluster_id must be an int")
        if next_id in seen_ids or (seen_ids and next_id <= max(seen_ids)):
            raise ValueError(
                "Invalid template cache: next_cluster_id conflicts with a cluster"
            )
        parser.next_cluster_id = next_id
        parser._rebuild_trie()
        return parser

    @classmethod
    def _validate_template_cache_config(
        cls,
        state: object,
        *,
        input_config: Mapping[str, object] | None,
        header_config: Mapping[str, object] | None,
        tokenizer_config: Mapping[str, object] | None,
    ) -> None:
        if not isinstance(state, Mapping):
            raise ValueError("Invalid template cache: root must be an object")
        version = state.get("version")
        if (
            isinstance(version, int)
            and not isinstance(version, bool)
            and version in {1, 2, 3}
        ):
            raise ValueError(
                f"Unsupported template cache version {version}; run learn again to rebuild the cache"
            )
        if version != 4 or isinstance(version, bool):
            raise ValueError(f"Unsupported template cache version {version!r}")
        if set(state) != cls._ROOT_FIELDS:
            raise ValueError("Invalid template cache: root fields are invalid")
        cached_input = cls._normalize_input_config(state["input"])
        cached_header = cls._normalize_header_config(state["header"])
        _ = cls._normalize_learning_config(state["learning"])
        cached_tokenizer = cls._normalize_tokenizer_config(state["tokenizer"])
        differences: list[str] = []
        if (
            input_config is not None
            and cached_input["mode"]
            != cls._normalize_input_config(input_config)["mode"]
        ):
            differences.append("input.mode")
        if header_config is not None:
            current_header = cls._normalize_header_config(header_config)
            differences.extend(
                f"header.{field}"
                for field in ("parse_structure", "strict_mode", "field_patterns")
                if cached_header[field] != current_header[field]
            )
        if tokenizer_config is not None:
            current_tokenizer = cls._normalize_tokenizer_config(tokenizer_config)
            differences.extend(
                f"tokenizer.{field}"
                for field in (
                    "delimiters",
                    "extra_delimiters",
                    "use_jieba",
                    "mask_patterns",
                )
                if cached_tokenizer[field] != current_tokenizer[field]
            )
        if differences:
            raise ValueError(
                "Template cache configuration mismatch: " + ", ".join(differences)
            )

    @staticmethod
    def _source_from_json(raw: object) -> TokenSource:
        if not isinstance(raw, Mapping):
            raise ValueError("Invalid template cache: source must be an object")
        kind = raw.get("kind")
        if kind == "plain" and set(raw) == {"kind"}:
            return PlainTokenSource()
        if kind == "regex" and set(raw) == {"kind", "mask_name"}:
            name = raw.get("mask_name")
            if not isinstance(name, str) or not name.strip():
                raise ValueError(
                    "Invalid template cache: regex mask_name must be non-empty"
                )
            return RegexTokenSource(mask_name=name)
        raise ValueError("Invalid template cache: invalid token source")

    @classmethod
    def _template_token_from_json(cls, raw: object) -> TemplateToken:
        if not isinstance(raw, Mapping):
            raise ValueError("Invalid template cache: template token must be an object")
        kind = raw.get("kind")
        expected = (
            {"kind", "text", "sources"}
            if kind == "literal"
            else {"kind", "var_name", "sources"}
        )
        if kind not in {"literal", "variable"} or set(raw) != expected:
            raise ValueError("Invalid template cache: invalid template token fields")
        raw_sources = raw.get("sources")
        if not isinstance(raw_sources, list):
            raise ValueError("Invalid template cache: sources must be a list")
        sources = tuple(cls._source_from_json(item) for item in raw_sources)
        if not sources or normalize_sources(sources) != sources:
            raise ValueError(
                "Invalid template cache: sources must be unique and canonical"
            )
        if kind == "literal":
            text = raw.get("text")
            if not isinstance(text, str) or not text:
                raise ValueError(
                    "Invalid template cache: literal text must be non-empty"
                )
            return LiteralTemplateToken(text=text, sources=sources)
        name = raw.get("var_name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Invalid template cache: variable name must be non-empty")
        return VariableTemplateToken(var_name=name.strip(), sources=sources)

    @staticmethod
    def _normalize_input_config(raw: object) -> dict[str, str]:
        if not isinstance(raw, Mapping) or set(raw) != {"mode"}:
            raise ValueError("Invalid template cache: input fields are invalid")
        mode = raw.get("mode")
        if not isinstance(mode, str) or mode not in {"single", "multiline"}:
            raise ValueError(
                "Invalid template cache: input.mode must be 'single' or 'multiline'"
            )
        return {"mode": mode}

    @staticmethod
    def _normalize_learning_config(raw: object) -> dict[str, object]:
        if not isinstance(raw, Mapping) or set(raw) != {"shuffle", "random_seed"}:
            raise ValueError("Invalid template cache: learning fields are invalid")
        shuffle, seed = raw.get("shuffle"), raw.get("random_seed")
        if not isinstance(shuffle, bool):
            raise ValueError("Invalid template cache: learning.shuffle must be a bool")
        if seed is not None and (not isinstance(seed, int) or isinstance(seed, bool)):
            raise ValueError(
                "Invalid template cache: learning.random_seed must be an int or null"
            )
        return {"shuffle": shuffle, "random_seed": seed}

    @staticmethod
    def _normalize_header_config(raw: object) -> dict[str, object]:
        fields = {"parse_structure", "strict_mode", "field_patterns"}
        if not isinstance(raw, Mapping) or set(raw) != fields:
            raise ValueError("Invalid template cache: header fields are invalid")
        structure, strict, patterns = (
            raw.get("parse_structure"),
            raw.get("strict_mode"),
            raw.get("field_patterns"),
        )
        if not isinstance(structure, str) or not structure:
            raise ValueError(
                "Invalid template cache: header.parse_structure must be non-empty"
            )
        if not isinstance(strict, bool):
            raise ValueError(
                "Invalid template cache: header.strict_mode must be a bool"
            )
        if not isinstance(patterns, Mapping) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in patterns.items()
        ):
            raise ValueError(
                "Invalid template cache: header.field_patterns must map strings to strings"
            )
        return {
            "parse_structure": structure,
            "strict_mode": strict,
            "field_patterns": dict(patterns),
        }

    @staticmethod
    def _normalize_tokenizer_config(raw: object) -> dict[str, object]:
        fields = {"delimiters", "extra_delimiters", "use_jieba", "mask_patterns"}
        if not isinstance(raw, Mapping) or set(raw) != fields:
            raise ValueError("Invalid template cache: tokenizer fields are invalid")
        delimiters, extras = raw.get("delimiters"), raw.get("extra_delimiters")
        use_jieba, masks = raw.get("use_jieba"), raw.get("mask_patterns")
        if not isinstance(delimiters, str):
            raise ValueError(
                "Invalid template cache: tokenizer.delimiters must be a string"
            )
        if not isinstance(extras, list) or not all(isinstance(x, str) for x in extras):
            raise ValueError(
                "Invalid template cache: tokenizer.extra_delimiters must be strings"
            )
        if not isinstance(use_jieba, bool):
            raise ValueError(
                "Invalid template cache: tokenizer.use_jieba must be a bool"
            )
        if not isinstance(masks, list):
            raise ValueError(
                "Invalid template cache: tokenizer.mask_patterns must be a list"
            )
        normalized_masks: list[dict[str, str]] = []
        for mask in masks:
            if not isinstance(mask, Mapping) or set(mask) != {"name", "pattern"}:
                raise ValueError(
                    "Invalid template cache: mask pattern fields are invalid"
                )
            name, pattern = mask.get("name"), mask.get("pattern")
            if (
                not isinstance(name, str)
                or not name
                or not isinstance(pattern, str)
                or not pattern
            ):
                raise ValueError(
                    "Invalid template cache: mask name and pattern must be non-empty strings"
                )
            normalized_masks.append({"name": name, "pattern": pattern})
        return {
            "delimiters": delimiters,
            "extra_delimiters": list(extras),
            "use_jieba": use_jieba,
            "mask_patterns": normalized_masks,
        }
