from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import tomllib

from .header import CONTEXT_ONLY_STRUCTURE
from .tokenizer import DEFAULT_DELIMITERS


@dataclass
class SpellConfig:
    tau_ratio: float = 0.5


@dataclass
class TokenizerConfig:
    delimiters: str = DEFAULT_DELIMITERS
    extra_delimiters: tuple[str, ...] = ()
    mask_patterns: tuple[str, ...] = ()
    use_jieba: bool = True


@dataclass
class HeaderConfig:
    parse_structure: str = CONTEXT_ONLY_STRUCTURE
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
    spell: SpellConfig
    tokenizer: TokenizerConfig
    header: HeaderConfig
    output: OutputConfig


def read_toml_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists() or not config_path.is_file():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with config_path.open("rb") as fp:
        return tomllib.load(fp)


def parse_demo_config(data: Mapping[str, Any]) -> DemoConfig:
    if not isinstance(data, Mapping):
        raise ValueError("Config root must be a TOML table")

    spell_data = data.get("spell", {})
    tokenizer_data = data.get("tokenizer", {})
    header_data = data.get("header", {})
    output_data = data.get("output", {})

    if not isinstance(spell_data, Mapping):
        raise ValueError("spell must be a TOML table")
    if not isinstance(tokenizer_data, Mapping):
        raise ValueError("tokenizer must be a TOML table")
    if not isinstance(header_data, Mapping):
        raise ValueError("header must be a TOML table")
    if not isinstance(output_data, Mapping):
        raise ValueError("output must be a TOML table")

    spell = SpellConfig(
        tau_ratio=float(spell_data.get("tau_ratio", 0.5)),
    )

    tokenizer = TokenizerConfig(
        delimiters=str(tokenizer_data.get("delimiters", DEFAULT_DELIMITERS)),
        extra_delimiters=tuple(
            str(item) for item in tokenizer_data.get("extra_delimiters", [])
        ),
        mask_patterns=tuple(
            str(item) for item in tokenizer_data.get("mask_patterns", [])
        ),
        use_jieba=bool(tokenizer_data.get("use_jieba", True)),
    )

    parse_structure = str(header_data.get("parse_structure", CONTEXT_ONLY_STRUCTURE))
    if "<context>" not in parse_structure:
        raise ValueError("header.parse_structure must contain '<context>'")

    raw_field_patterns = header_data.get("field_patterns", {})
    if not isinstance(raw_field_patterns, Mapping):
        raise ValueError("header.field_patterns must be a TOML table")

    field_patterns: dict[str, str] = {
        str(key): str(value)
        for key, value in raw_field_patterns.items()
        if value is not None and str(value) != ""
    }

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
        spell=spell,
        tokenizer=tokenizer,
        header=header,
        output=output,
    )


def load_demo_config(config_path: Path) -> DemoConfig:
    return parse_demo_config(read_toml_config(config_path))
