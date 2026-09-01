from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import cast

import regex

from .header import HeaderConfigurationError, RegexHeaderParser
from .models import MaskPattern
from .tokenizer import DEFAULT_DELIMITERS


class InputMode(str, Enum):
    SINGLE = "single"
    MULTILINE = "multiline"


@dataclass(frozen=True)
class InputConfig:
    mode: InputMode


@dataclass(frozen=True)
class LearningConfig:
    shuffle: bool = False
    random_seed: int | None = None

@dataclass
class SpellConfig:
    tau_ratio: float = 0.5


@dataclass
class TokenizerConfig:
    delimiters: str = DEFAULT_DELIMITERS
    extra_delimiters: tuple[str, ...] = ()
    mask_patterns: tuple[MaskPattern, ...] = ()
    use_jieba: bool = True


@dataclass
class HeaderConfig:
    parse_structure: str
    strict_mode: bool = False
    field_patterns: dict[str, str] = field(default_factory=dict)


@dataclass
class OutputConfig:
    dir: Path = Path("output")
    parsed_file: str = "parsed_results.jsonl"
    template_file: str = "templates.txt"
    show_tokens: bool = False


@dataclass
class DemoConfig:
    input: InputConfig
    spell: SpellConfig
    tokenizer: TokenizerConfig
    header: HeaderConfig
    output: OutputConfig
    learning: LearningConfig = field(default_factory=LearningConfig)


def read_toml_config(config_path: Path) -> dict[str, object]:
    if not config_path.exists() or not config_path.is_file():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with config_path.open("rb") as fp:
        return cast(dict[str, object], tomllib.load(fp))


def parse_demo_config(data: Mapping[str, object]) -> DemoConfig:

    input_data = data.get("input")
    spell_data = data.get("spell", {})
    tokenizer_data = data.get("tokenizer", {})
    header_data = data.get("header")
    output_data = data.get("output", {})
    learning_data = data.get("learning", {})

    if not isinstance(input_data, Mapping):
        raise TypeError("input must be a TOML table")
    if "mode" not in input_data:
        raise ValueError("input.mode is required")
    raw_mode = input_data["mode"]
    if not isinstance(raw_mode, str):
        raise TypeError("input.mode must be 'single' or 'multiline'")
    try:
        input_config = InputConfig(mode=InputMode(raw_mode))
    except ValueError as exc:
        raise ValueError("input.mode must be 'single' or 'multiline'") from exc
    if not isinstance(spell_data, Mapping):
        raise TypeError("spell must be a TOML table")
    spell_data = cast(Mapping[str, object], spell_data)
    if not isinstance(tokenizer_data, Mapping):
        raise TypeError("tokenizer must be a TOML table")
    tokenizer_data = cast(Mapping[str, object], tokenizer_data)
    if not isinstance(header_data, Mapping):
        raise TypeError("header must be a TOML table")
    if not isinstance(output_data, Mapping):
        raise TypeError("output must be a TOML table")
    if not isinstance(learning_data, Mapping):
        raise TypeError("learning must be a TOML table")
    header_data = cast(Mapping[str, object], header_data)
    output_data = cast(Mapping[str, object], output_data)
    learning_data = cast(Mapping[str, object], learning_data)

    raw_shuffle = learning_data.get("shuffle", False)
    if not isinstance(raw_shuffle, bool):
        raise TypeError("learning.shuffle must be a bool")
    raw_random_seed = learning_data.get("random_seed")
    if raw_random_seed is not None and (
        not isinstance(raw_random_seed, int) or isinstance(raw_random_seed, bool)
    ):
        raise TypeError("learning.random_seed must be an int")
    learning = LearningConfig(
        shuffle=raw_shuffle,
        random_seed=raw_random_seed,
    )

    spell = SpellConfig(
        tau_ratio=float(cast(str | int | float, spell_data.get("tau_ratio", 0.5))),
    )

    mask_patterns = _parse_mask_patterns(tokenizer_data.get("mask_patterns", []))
    tokenizer = TokenizerConfig(
        delimiters=str(tokenizer_data.get("delimiters", DEFAULT_DELIMITERS)),
        extra_delimiters=tuple(
            str(item) for item in _as_list(tokenizer_data.get("extra_delimiters", []))
        ),
        mask_patterns=mask_patterns,
        use_jieba=bool(tokenizer_data.get("use_jieba", True)),
    )

    if "parse_structure" not in header_data:
        raise ValueError("header.parse_structure is required")
    parse_structure = header_data["parse_structure"]
    if not isinstance(parse_structure, str):
        raise TypeError("header.parse_structure must be a string")

    raw_field_patterns = header_data.get("field_patterns", {})
    if not isinstance(raw_field_patterns, Mapping):
        raise TypeError("header.field_patterns must be a TOML table")

    field_patterns: dict[str, str] = {}
    for key, value in cast(Mapping[object, object], raw_field_patterns).items():
        if not isinstance(value, str) or not value:
            raise ValueError(f"header.field_patterns.{key} must be a non-empty regex")
        field_patterns[str(key)] = value

    try:
        header_parser = RegexHeaderParser(
            parse_structure=parse_structure,
            field_patterns=field_patterns,
            strict_mode=bool(header_data.get("strict_mode", False)),
        )
    except HeaderConfigurationError as exc:
        raise ValueError(str(exc)) from exc

    if input_config.mode is InputMode.MULTILINE:
        context_start = parse_structure.index("<context>")
        prefix = parse_structure[:context_start]
        suffix = parse_structure[context_start + len("<context>") :]
        if suffix.strip():
            raise ValueError("multiline_context_not_last")
        if not prefix:
            raise ValueError("multiline_header_missing")
        if header_parser.header_prefix_matches_empty:
            raise ValueError("multiline_header_matches_empty")

    header = HeaderConfig(
        parse_structure=parse_structure,
        strict_mode=bool(header_data.get("strict_mode", False)),
        field_patterns=field_patterns,
    )

    output = OutputConfig(
        dir=Path(str(output_data.get("dir", "output"))),
        parsed_file=str(output_data.get("parsed_file", "parsed_results.jsonl")),
        template_file=str(output_data.get("template_file", "templates.txt")),
        show_tokens=bool(output_data.get("show_tokens", False)),
    )

    return DemoConfig(
        input=input_config,
        spell=spell,
        tokenizer=tokenizer,
        header=header,
        output=output,
        learning=learning,
    )


def load_demo_config(config_path: Path) -> DemoConfig:
    return parse_demo_config(read_toml_config(config_path))


def _parse_mask_patterns(raw_patterns: object) -> tuple[MaskPattern, ...]:
    path = "tokenizer.mask_patterns"
    if not isinstance(raw_patterns, list):
        raise TypeError(f"{path} must be an array of TOML tables")

    masks: list[MaskPattern] = []
    names: set[str] = set()
    for index, raw_mask in enumerate(cast(list[object], raw_patterns)):
        item_path = f"{path}[{index}]"
        if not isinstance(raw_mask, Mapping):
            raise TypeError(f"{item_path} must be a TOML table")

        if "name" not in raw_mask:
            raise ValueError(f"{item_path}.name is required")
        raw_name = raw_mask["name"]
        if not isinstance(raw_name, str):
            raise TypeError(f"{item_path}.name must be a string")
        name = raw_name.strip()
        if not name:
            raise ValueError(f"{item_path}.name must be non-empty")
        if name in names:
            raise ValueError(f"{path} contains duplicate name {name!r}")

        if "pattern" not in raw_mask:
            raise ValueError(f"{item_path}.pattern is required")
        pattern = raw_mask["pattern"]
        if not isinstance(pattern, str):
            raise TypeError(f"{item_path}.pattern must be a string")
        if not pattern.strip():
            raise ValueError(f"{item_path}.pattern must be non-empty")
        try:
            compiled = regex.compile(pattern)
        except regex.error as exc:
            raise ValueError(f"{item_path}.pattern is an invalid regex: {exc}") from exc
        if compiled.search("") is not None:
            raise ValueError(f"{item_path}.pattern must not match the empty string")

        names.add(name)
        masks.append(MaskPattern(name=name, pattern=pattern))
    return tuple(masks)


def _as_list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise TypeError("Expected a TOML array")
    return cast(list[object], value)