from __future__ import annotations

from pin_xie import (
    DemoConfig,
    HeaderConfig,
    InputConfig,
    InputMode,
    OutputConfig,
    PinXieEngine,
    SpellConfig,
    TokenizerConfig,
)


def build_config(
    *,
    parse_structure: str,
    field_patterns: dict[str, str],
    mode: InputMode = InputMode.SINGLE,
) -> DemoConfig:
    return DemoConfig(
        input=InputConfig(mode=mode),
        spell=SpellConfig(),
        tokenizer=TokenizerConfig(),
        header=HeaderConfig(
            parse_structure=parse_structure,
            field_patterns=field_patterns,
        ),
        output=OutputConfig(),
    )


def test_validate_header_extraction_reports_field_pattern_mismatch() -> None:
    config = build_config(
        parse_structure="<ts> <level> <context>",
        field_patterns={
            "ts": r"\d{4}-\d{2}-\d{2}",
            "level": r"INFO|ERROR",
        },
    )

    report = PinXieEngine.validate_header_extraction(
        config,
        ["2026-03-20 INFO ok", "2026-03-20 WARN timeout"],
    )

    assert report.requires_header_validation is True
    assert report.total_samples == 2
    assert report.successful_samples == 1
    assert len(report.failures) == 1

    failure = report.failures[0]
    assert failure.index == 2
    assert failure.sample == "2026-03-20 WARN timeout"
    assert failure.stage == "sample"
    assert failure.reason == "field_pattern_mismatch"
    assert failure.field == "level"
    assert failure.pattern == "INFO|ERROR"
    assert failure.structure_part is None
    assert (
        "Field <level> does not match header.field_patterns.level: value=WARN"
        in failure.message
    )
    assert (
        "trace: <ts>[OK] pattern='\\d{4}-\\d{2}-\\d{2}' value='2026-03-20'"
        in failure.message
    )
    assert "<level>[FAIL] pattern='INFO|ERROR' value='WARN'" in failure.message


def test_validate_header_extraction_reports_structure_mismatch() -> None:
    config = build_config(
        parse_structure="[<ts>] <context>",
        field_patterns={"ts": r"\d{4}-\d{2}-\d{2}"},
    )

    report = PinXieEngine.validate_header_extraction(config, ["2026-03-20 timeout"])

    assert report.requires_header_validation is True
    assert report.successful_samples == 0
    assert len(report.failures) == 1

    failure = report.failures[0]
    assert failure.reason == "parse_structure_mismatch"
    assert failure.structure_part == "start"
    assert failure.field is None
    assert failure.pattern is None
    assert failure.message == (
        "Sample does not match header.parse_structure at start; "
        "trace: [FAIL] literal='['"
    )


def test_validate_header_extraction_reports_config_failure() -> None:
    config = build_config(
        parse_structure="<ts> <level> <context>",
        field_patterns={"ts": r"\d{4}-\d{2}-\d{2}"},
    )

    report = PinXieEngine.validate_header_extraction(config, ["2026-03-20 INFO ok"])

    assert report.requires_header_validation is True
    assert report.total_samples == 1
    assert report.successful_samples == 0
    assert len(report.failures) == 1

    failure = report.failures[0]
    assert failure.index == 0
    assert failure.sample == ""
    assert failure.stage == "config"
    assert failure.reason == "field_pattern_missing"
    assert failure.field == "level"
    assert failure.pattern is None
    assert failure.structure_part is None
    assert (
        failure.message
        == "Missing regex pattern for placeholder <level> in header.field_patterns"
    )


def test_validate_config_path_reports_missing_context(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[input]
mode = 'single'

[header]
parse_structure = '<ts> <message>'

[header.field_patterns]
ts = '\\d{4}-\\d{2}-\\d{2}'
message = '.*'
""".strip(),
        encoding="utf-8",
    )

    report = PinXieEngine.validate_config_path(config_path, ["2026-03-20 hello"])

    assert report.requires_header_validation is True
    assert report.total_samples == 1
    assert report.successful_samples == 0
    assert len(report.failures) == 1

    failure = report.failures[0]
    assert failure.index == 0
    assert failure.sample == ""
    assert failure.stage == "config"
    assert failure.reason == "parse_structure_missing_context"
    assert failure.message == "header.parse_structure must contain '<context>'"


def test_validate_header_extraction_skips_pure_context() -> None:
    config = build_config(parse_structure="<context>", field_patterns={})

    report = PinXieEngine.validate_header_extraction(config, ["a", "b"])

    assert report.requires_header_validation is False
    assert report.total_samples == 2
    assert report.successful_samples == 2
    assert report.failures == []


def test_validate_header_extraction_validates_literal_prefixed_context() -> None:
    config = build_config(parse_structure="13abc<context>", field_patterns={})

    report = PinXieEngine.validate_header_extraction(config, ["13abcok", "wrong"])

    assert report.requires_header_validation is True
    assert report.total_samples == 2
    assert report.successful_samples == 1
    assert len(report.failures) == 1

    failure = report.failures[0]
    assert failure.index == 2
    assert failure.sample == "wrong"
    assert failure.reason == "parse_structure_mismatch"
    assert failure.structure_part == "start"


def test_parse_config_requires_input_and_header_tables() -> None:
    import pytest

    with pytest.raises(TypeError, match="input must be a TOML table"):
        PinXieEngine.parse_config_data({"header": {"parse_structure": "<context>"}})
    with pytest.raises(TypeError, match="header must be a TOML table"):
        PinXieEngine.parse_config_data({"input": {"mode": "single"}})


def test_parse_config_rejects_invalid_input_modes() -> None:
    import pytest

    base = {"header": {"parse_structure": "<context>"}}
    with pytest.raises(ValueError, match="input.mode is required"):
        PinXieEngine.parse_config_data({"input": {}, **base})
    with pytest.raises(ValueError, match="input.mode must be"):
        PinXieEngine.parse_config_data({"input": {"mode": "automatic"}, **base})


def test_multiline_config_constraints() -> None:
    import pytest

    def parse(structure: str, patterns: dict[str, str] | None = None) -> None:
        PinXieEngine.parse_config_data(
            {
                "input": {"mode": "multiline"},
                "header": {
                    "parse_structure": structure,
                    "field_patterns": patterns or {},
                },
            }
        )

    with pytest.raises(ValueError, match="multiline_header_missing"):
        parse("<context>")
    with pytest.raises(ValueError, match="multiline_context_not_last"):
        parse("<context> suffix")
    with pytest.raises(ValueError, match="multiline_context_not_last"):
        parse("<context> <level>", {"level": "INFO"})
    with pytest.raises(ValueError, match="multiline_header_matches_empty"):
        parse("<level><context>", {"level": ".*"})

    parse("LOG <context>")
    parse("<level> <context>", {"level": "INFO|ERROR"})


def test_header_line_is_anchored_and_parse_supports_multiline_context() -> None:
    from pin_xie import RegexHeaderParser

    parser = RegexHeaderParser(
        "<level> <context>", {"level": "INFO|ERROR"}, strict_mode=True
    )
    assert parser.is_header_line("INFO started") is True
    assert parser.is_header_line(" INFO started") is False
    assert parser.is_header_line("WARN started") is False
    assert parser.is_header_line("INFO first\ncontinued") is False

    result = parser.parse("ERROR failed\n  traceback\n")
    assert result.matched is True
    assert result.context == "failed\n  traceback"


def test_explicit_leading_space_and_header_only_line() -> None:
    from pin_xie import RegexHeaderParser

    parser = RegexHeaderParser(" <level> <context>", {"level": "INFO"})
    assert parser.is_header_line(" INFO ") is True
    assert parser.is_header_line("INFO ") is False
    assert parser.parse(" INFO ").context == ""


def test_multiline_sample_requires_header_and_preserves_leading_whitespace() -> None:
    config = build_config(
        mode=InputMode.MULTILINE,
        parse_structure="<level> <context>",
        field_patterns={"level": "INFO"},
    )
    report = PinXieEngine.validate_header_extraction(
        config, [" INFO bad\ncontinuation\n", "INFO good\n  continuation\n"]
    )
    assert report.total_samples == 2
    assert report.successful_samples == 1
    assert report.failures[0].reason == "sample_first_line_not_header"
    assert report.failures[0].sample.startswith(" INFO")