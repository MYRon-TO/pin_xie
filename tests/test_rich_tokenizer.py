# pyright: standard

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from pin_xie.config import parse_demo_config
from pin_xie.models import (
    InputToken,
    LiteralTemplateToken,
    MaskPattern,
    ParameterCapture,
    PlainTokenSource,
    RegexTokenSource,
    VariableTemplateToken,
    input_token_to_json,
    normalize_sources,
    parameter_capture_to_json,
    template_token_to_json,
)
from pin_xie.tokenizer import LogTokenizer, tokenize


def _config(mask_patterns: object) -> Mapping[str, Any]:
    return {
        "input": {"mode": "single"},
        "tokenizer": {"mask_patterns": mask_patterns},
        "header": {"parse_structure": "<context>"},
    }


def test_named_mask_config_preserves_order_and_pattern_text() -> None:
    config = parse_demo_config(
        _config(
            [
                {"name": " first ", "pattern": r"\d+ "},
                {"name": "second", "pattern": r"[a-z]+"},
            ]
        )
    )

    assert config.tokenizer.mask_patterns == (
        MaskPattern(name="first", pattern=r"\d+ "),
        MaskPattern(name="second", pattern=r"[a-z]+"),
    )


@pytest.mark.parametrize(
    ("masks", "reason"),
    [
        (["old-style"], "TOML table"),
        ([{"pattern": r"\d+"}], "name is required"),
        ([{"name": "x"}], "pattern is required"),
        ([{"name": "  ", "pattern": r"\d+"}], "name must be non-empty"),
        ([{"name": "x", "pattern": " "}], "pattern must be non-empty"),
        ([{"name": 1, "pattern": r"\d+"}], "name must be a string"),
        ([{"name": "x", "pattern": 1}], "pattern must be a string"),
        (
            [
                {"name": "same", "pattern": "a"},
                {"name": " same ", "pattern": "b"},
            ],
            "duplicate name",
        ),
        ([{"name": "x", "pattern": "("}], "invalid regex"),
        ([{"name": "x", "pattern": "a*"}], "empty string"),
    ],
)
def test_invalid_mask_config_is_rejected(masks: object, reason: str) -> None:
    with pytest.raises((TypeError, ValueError)) as exc_info:
        parse_demo_config(_config(masks))

    message = str(exc_info.value)
    assert "tokenizer.mask_patterns" in message
    assert reason in message


def test_mask_config_must_be_an_array() -> None:
    with pytest.raises(TypeError, match="tokenizer.mask_patterns"):
        parse_demo_config(_config({"name": "x", "pattern": "x"}))


def test_plain_tokens_have_plain_source() -> None:
    assert tokenize("hello world") == [
        InputToken("hello", PlainTokenSource()),
        InputToken("world", PlainTokenSource()),
    ]


def test_mask_source_priority_and_protected_content() -> None:
    tokenizer = LogTokenizer(
        mask_patterns=(
            MaskPattern("first", r"\d+(?:\.\d+)+"),
            MaskPattern("second", r"\d+\.\d+"),
        )
    )

    assert tokenizer.tokenize("version=10.20.30") == [
        InputToken("version", PlainTokenSource()),
        InputToken("10.20.30", RegexTokenSource("first")),
    ]


def test_user_named_and_numbered_groups_do_not_control_mask_identity() -> None:
    tokenizer = LogTokenizer(
        mask_patterns=(
            MaskPattern("word", r"(?P<__pin_xie_mask_0>(foo))"),
            MaskPattern("number", r"(?P<user_number>\d+)-(\w+)"),
        )
    )

    assert tokenizer.tokenize("foo 12-tail") == [
        InputToken("foo", RegexTokenSource("word")),
        InputToken("12-tail", RegexTokenSource("number")),
    ]


def test_mask_is_not_split_by_delimiters_or_jieba() -> None:
    tokenizer = LogTokenizer(
        mask_patterns=(MaskPattern("message", r"中文:内容"),), use_jieba=True
    )

    assert tokenizer.tokenize("prefix 中文:内容 suffix") == [
        InputToken("prefix", PlainTokenSource()),
        InputToken("中文:内容", RegexTokenSource("message")),
        InputToken("suffix", PlainTokenSource()),
    ]


def test_empty_and_multiline_text() -> None:
    tokenizer = LogTokenizer(use_jieba=False)
    assert tokenizer.tokenize("") == []
    assert tokenizer.tokenize("first line\nsecond line") == [
        InputToken("first", PlainTokenSource()),
        InputToken("line", PlainTokenSource()),
        InputToken("second", PlainTokenSource()),
        InputToken("line", PlainTokenSource()),
    ]


def test_sources_are_normalized_and_serialized_explicitly() -> None:
    plain = PlainTokenSource()
    alpha = RegexTokenSource("alpha")
    zebra = RegexTokenSource("zebra")
    unordered = (zebra, plain, alpha, zebra)
    expected_sources = (plain, alpha, zebra)

    assert normalize_sources(unordered) == expected_sources
    literal = LiteralTemplateToken("value", unordered)
    variable = VariableTemplateToken("var_1", unordered)
    capture = ParameterCapture(2, "var_1", "value", unordered)
    assert literal.sources == variable.sources == capture.sources == expected_sources
    assert input_token_to_json(InputToken("value", alpha)) == {
        "text": "value",
        "source": {"kind": "regex", "mask_name": "alpha"},
    }
    assert template_token_to_json(literal) == {
        "kind": "literal",
        "text": "value",
        "sources": [
            {"kind": "plain"},
            {"kind": "regex", "mask_name": "alpha"},
            {"kind": "regex", "mask_name": "zebra"},
        ],
    }
    assert (
        parameter_capture_to_json(capture)["sources"]
        == template_token_to_json(variable)["sources"]
    )
