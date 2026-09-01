from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, TypeAlias

JsonObject: TypeAlias = dict[str, object]


@dataclass(frozen=True)
class MaskPattern:
    name: str
    pattern: str


@dataclass(frozen=True)
class PlainTokenSource:
    kind: Literal["plain"] = "plain"


@dataclass(frozen=True)
class RegexTokenSource:
    mask_name: str
    kind: Literal["regex"] = "regex"


TokenSource: TypeAlias = PlainTokenSource | RegexTokenSource


@dataclass(frozen=True)
class InputToken:
    text: str
    source: TokenSource


@dataclass(frozen=True)
class LiteralTemplateToken:
    text: str
    sources: tuple[TokenSource, ...]
    kind: Literal["literal"] = "literal"

    def __post_init__(self) -> None:
        object.__setattr__(self, "sources", normalize_sources(self.sources))


@dataclass(frozen=True)
class VariableTemplateToken:
    var_name: str
    sources: tuple[TokenSource, ...]
    kind: Literal["variable"] = "variable"

    def __post_init__(self) -> None:
        object.__setattr__(self, "sources", normalize_sources(self.sources))


TemplateToken: TypeAlias = LiteralTemplateToken | VariableTemplateToken


@dataclass(frozen=True)
class ParameterCapture:
    template_token_index: int
    var_name: str
    value: str
    sources: tuple[TokenSource, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "sources", normalize_sources(self.sources))


def normalize_sources(sources: Iterable[TokenSource]) -> tuple[TokenSource, ...]:
    """Deduplicate sources and return their canonical stable order."""
    return tuple(
        sorted(
            set(sources),
            key=lambda source: (0, "")
            if source.kind == "plain"
            else (1, source.mask_name),
        )
    )


def input_token_text(token: InputToken) -> str:
    return token.text


def is_variable_template_token(token: TemplateToken) -> bool:
    return token.kind == "variable"


def template_literal_text(token: TemplateToken) -> str | None:
    return token.text if token.kind == "literal" else None


def token_source_to_json(source: TokenSource) -> JsonObject:
    if source.kind == "plain":
        return {"kind": "plain"}
    return {"kind": "regex", "mask_name": source.mask_name}


def input_token_to_json(token: InputToken) -> JsonObject:
    return {"text": token.text, "source": token_source_to_json(token.source)}


def template_token_to_json(token: TemplateToken) -> JsonObject:
    sources = [token_source_to_json(source) for source in token.sources]
    if token.kind == "literal":
        return {"kind": "literal", "text": token.text, "sources": sources}
    return {"kind": "variable", "var_name": token.var_name, "sources": sources}


def parameter_capture_to_json(capture: ParameterCapture) -> JsonObject:
    return {
        "template_token_index": capture.template_token_index,
        "var_name": capture.var_name,
        "value": capture.value,
        "sources": [token_source_to_json(source) for source in capture.sources],
    }


def mask_pattern_to_json(mask: MaskPattern) -> JsonObject:
    return {"name": mask.name, "pattern": mask.pattern}
