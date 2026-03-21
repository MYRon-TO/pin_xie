from __future__ import annotations

from pin_xie import (
    DemoConfig,
    HeaderConfig,
    OutputConfig,
    PinXieEngine,
    SpellConfig,
    TokenizerConfig,
)


def build_config(*, parse_structure: str, field_patterns: dict[str, str]) -> DemoConfig:
    return DemoConfig(
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
