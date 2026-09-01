# pyright: standard

from __future__ import annotations

import json
from pathlib import Path

import pytest

import pin_xie
from pin_xie import (
    DemoConfig,
    HeaderConfig,
    InputConfig,
    InputMode,
    InputToken,
    LiteralTemplateToken,
    MaskPattern,
    OutputConfig,
    ParameterCapture,
    PinXieEngine,
    PlainTokenSource,
    RegexTokenSource,
    SpellConfig,
    TemplateToken,
    TokenizerConfig,
    TokenSource,
    VariableTemplateToken,
)


def build_engine(tmp_path: Path, *, show_tokens: bool = True) -> PinXieEngine:
    return PinXieEngine(
        DemoConfig(
            input=InputConfig(mode=InputMode.SINGLE),
            spell=SpellConfig(tau_ratio=0.2),
            tokenizer=TokenizerConfig(
                use_jieba=False,
                mask_patterns=(
                    MaskPattern("ipv4", r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
                    MaskPattern("number", r"\b\d+\b"),
                ),
            ),
            header=HeaderConfig(
                parse_structure="<level> <context>",
                field_patterns={"level": r"INFO|ERROR"},
                strict_mode=True,
            ),
            output=OutputConfig(dir=tmp_path, show_tokens=show_tokens),
        )
    )


def generalized_record(engine: PinXieEngine):
    engine.process_log("INFO connect from host 10.0.0.1", line_id=1)
    return engine.process_log("ERROR connect from host client", line_id=2)


def test_rich_record_and_explicit_payload(tmp_path: Path) -> None:
    engine = build_engine(tmp_path)
    record = generalized_record(engine)
    payload = engine._record_to_payload(record, show_tokens=True)

    assert record.template == "connect from host <VAR:var_0>"
    assert all(isinstance(token, (LiteralTemplateToken, VariableTemplateToken)) for token in record.template_tokens)
    assert all(isinstance(parameter, ParameterCapture) for parameter in record.parameters)
    assert all(isinstance(token, InputToken) for token in record.tokens or [])
    assert payload["template_tokens"] == [
        {"kind": "literal", "text": "connect", "sources": [{"kind": "plain"}]},
        {"kind": "literal", "text": "from", "sources": [{"kind": "plain"}]},
        {"kind": "literal", "text": "host", "sources": [{"kind": "plain"}]},
        {
            "kind": "variable",
            "var_name": "var_0",
            "sources": [
                {"kind": "plain"},
                {"kind": "regex", "mask_name": "ipv4"},
            ],
        },
    ]
    assert payload["parameters"] == [
        {
            "template_token_index": 3,
            "var_name": "var_0",
            "value": "client",
            "sources": [{"kind": "plain"}],
        }
    ]
    assert payload["tokens"] == [
        {"text": "connect", "source": {"kind": "plain"}},
        {"text": "from", "source": {"kind": "plain"}},
        {"text": "host", "source": {"kind": "plain"}},
        {"text": "client", "source": {"kind": "plain"}},
    ]
    assert "named_parameters" not in payload
    assert payload["header_level"] == "ERROR"
    assert (payload["line_id"], payload["end_line_id"], payload["physical_line_count"]) == (2, 2, 1)


def test_show_tokens_false_omits_key(tmp_path: Path) -> None:
    engine = build_engine(tmp_path, show_tokens=False)
    payload = engine._record_to_payload(generalized_record(engine), show_tokens=False)
    assert "tokens" not in payload


def test_variable_name_api_is_atomic_and_validated(tmp_path: Path) -> None:
    engine = build_engine(tmp_path)
    engine.process_log("INFO left fixed A middle fixed B end")
    engine.process_log("INFO left fixed X middle fixed Y end")
    cluster_id = engine.parser.all_clusters()[0].cluster_id

    assert engine.get_template_variable_names(cluster_id) == {0: "var_0", 1: "var_1"}
    engine.set_template_variable_name(cluster_id, 0, "first")
    assert engine.get_template_variable_names(cluster_id)[0] == "first"
    engine.set_template_variable_name(cluster_id, 0, None)
    assert engine.get_template_variable_names(cluster_id)[0] == "var_0"
    with pytest.raises(ValueError, match="unique"):
        engine.set_template_variable_name(cluster_id, 0, "var_1")
    assert engine.get_template_variable_names(cluster_id) == {0: "var_0", 1: "var_1"}
    assert engine.set_template_variable_names(cluster_id, {0: "var_1", 1: "var_0"}) == {
        0: "var_1",
        1: "var_0",
    }


def test_template_summary_has_variable_sources_and_mask_names(tmp_path: Path) -> None:
    engine = build_engine(tmp_path)
    generalized_record(engine)
    summary_path = engine.write_template_summary(tmp_path / "templates.txt")
    summary = summary_path.read_text(encoding="utf-8")

    assert 'mask_patterns_count=2 mask_pattern_names=["ipv4", "number"]' in summary
    assert "variable[3]: var_name=var_0" in summary
    assert 'sources=[{"kind": "plain"}, {"kind": "regex", "mask_name": "ipv4"}]' in summary
    assert "variable_names:" not in summary


def test_public_rich_model_exports_exclude_internal_helpers() -> None:
    expected = {
        "MaskPattern",
        "InputToken",
        "LiteralTemplateToken",
        "VariableTemplateToken",
        "TemplateToken",
        "ParameterCapture",
        "PlainTokenSource",
        "RegexTokenSource",
        "TokenSource",
    }
    assert expected <= set(pin_xie.__all__)
    assert not {
        "input_token_to_json",
        "template_token_to_json",
        "parameter_capture_to_json",
        "normalize_sources",
    } & set(pin_xie.__all__)
    assert TemplateToken is not None and TokenSource is not None


def test_jsonl_is_serializable(tmp_path: Path) -> None:
    engine = build_engine(tmp_path)
    payload = engine._record_to_payload(generalized_record(engine), show_tokens=True)
    assert json.loads(json.dumps(payload)) == payload
    assert PlainTokenSource() == PlainTokenSource()
    assert RegexTokenSource("ipv4") == RegexTokenSource("ipv4")
