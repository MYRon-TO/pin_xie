from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
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
    result_format: str = "jsonl"
    show_tokens: bool = False


@dataclass
class DemoConfig:
    spell: SpellConfig
    tokenizer: TokenizerConfig
    header: HeaderConfig
    output: OutputConfig


def load_demo_config(config_path: Path) -> DemoConfig:
    if not config_path.exists() or not config_path.is_file():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with config_path.open("rb") as fp:
        data = tomllib.load(fp)

    spell_data = data.get("spell", {})
    tokenizer_data = data.get("tokenizer", {})
    header_data = data.get("header", {})
    output_data = data.get("output", {})

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
    if not isinstance(raw_field_patterns, dict):
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
        result_format=str(output_data.get("result_format", "jsonl")),
        show_tokens=bool(output_data.get("show_tokens", False)),
    )

    if output.result_format not in {"jsonl", "text"}:
        raise ValueError("output.result_format must be one of: jsonl, text")

    return DemoConfig(
        spell=spell,
        tokenizer=tokenizer,
        header=header,
        output=output,
    )
