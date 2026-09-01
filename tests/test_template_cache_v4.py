# pyright: standard

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from pin_xie.api import PinXieEngine
from pin_xie.models import InputToken, ParameterCapture
from pin_xie.parser import SpellParser
from pin_xie.tokenizer import LogTokenizer

INPUT: dict[str, Any] = {"mode": "single"}
HEADER: dict[str, Any] = {"parse_structure": "<context>", "strict_mode": False, "field_patterns": {}}
LEARNING: dict[str, Any] = {"shuffle": False, "random_seed": None}
TOKENIZER: dict[str, Any] = {
    "delimiters": " ",
    "extra_delimiters": [":"],
    "use_jieba": False,
    "mask_patterns": [
        {"name": "number", "pattern": r"\d+"},
        {"name": "word", "pattern": r"[a-z]+"},
    ],
}


def make_parser() -> SpellParser:
    from pin_xie.models import MaskPattern

    tokenizer = LogTokenizer(
        delimiters=" ", extra_delimiters=(":",), use_jieba=False,
        mask_patterns=(MaskPattern("number", r"\d+"), MaskPattern("word", r"[a-z]+")),
    )
    parser = SpellParser(tokenizer=tokenizer)
    parser.process("job 12 ok", line_id=1)
    parser.process("job abc ok", line_id=2)
    return parser


def state() -> dict[str, Any]:
    return make_parser().to_template_state(
        input_config=INPUT, header_config=HEADER, learning_config=LEARNING,
        tokenizer_config=TOKENIZER,
    )


def load(raw: dict[str, Any]) -> SpellParser:
    return SpellParser.from_template_state(
        raw, input_config=INPUT, header_config=HEADER, tokenizer_config=TOKENIZER,
    )


def test_v4_round_trip_preserves_rich_tokens_sources_and_trie() -> None:
    parser = make_parser()
    raw = state()
    assert raw["version"] == 4
    assert "variable_names" not in json.dumps(raw)
    token = raw["clusters"][0]["template_tokens"][1]  # type: ignore[index]
    assert token["kind"] == "variable"  # type: ignore[index]
    assert token["sources"] == [  # type: ignore[index]
        {"kind": "regex", "mask_name": "number"},
        {"kind": "regex", "mask_name": "word"},
    ]
    restored = load(raw)
    assert restored.all_clusters()[0].template_tokens == parser.all_clusters()[0].template_tokens
    result = restored.process("job 99 ok", update_model=False)
    assert result.cluster_id == 0
    assert all(isinstance(token, InputToken) for token in result.tokens)
    assert all(isinstance(param, ParameterCapture) for param in result.parameters)


@pytest.mark.parametrize("version", [1, 2, 3])
def test_old_versions_require_relearning(version: int) -> None:
    raw = state()
    raw["version"] = version
    with pytest.raises(ValueError, match="run learn again"):
        load(raw)


@pytest.mark.parametrize("field,value", [
    ("delimiters", "|"),
    ("extra_delimiters", []),
    ("use_jieba", True),
    ("mask_patterns", list(reversed(TOKENIZER["mask_patterns"]))),
])
def test_every_tokenizer_field_and_mask_order_is_compared(field: str, value: object) -> None:
    raw = state()
    raw_tokenizer = raw["tokenizer"]
    assert isinstance(raw_tokenizer, dict)
    raw_tokenizer[field] = value
    with pytest.raises(ValueError, match=f"tokenizer.{field}"):
        load(raw)


@pytest.mark.parametrize("mutator", [
    lambda raw: raw["clusters"][0]["template_tokens"][0].update(kind="bad"),
    lambda raw: raw["clusters"][0]["template_tokens"][0].update(text=3),
    lambda raw: raw["clusters"][0]["template_tokens"][1].update(var_name=" "),
    lambda raw: raw["clusters"][0]["template_tokens"][1]["sources"].append(
        raw["clusters"][0]["template_tokens"][1]["sources"][0]
    ),
    lambda raw: raw["clusters"][0]["template_tokens"][1]["sources"].reverse(),
])
def test_invalid_token_unions_and_sources_are_rejected(mutator) -> None:
    raw = state()
    mutator(raw)
    with pytest.raises(ValueError):
        load(raw)


def test_duplicate_variable_names_cluster_ids_and_next_id_are_rejected() -> None:
    raw = state()
    variable = copy.deepcopy(raw["clusters"][0]["template_tokens"][1])  # type: ignore[index]
    raw["clusters"][0]["template_tokens"].append(variable)  # type: ignore[index]
    with pytest.raises(ValueError, match="Variable names"):
        load(raw)

    raw = state()
    raw["clusters"].append(copy.deepcopy(raw["clusters"][0]))  # type: ignore[union-attr,index]
    with pytest.raises(ValueError, match="duplicate cluster_id"):
        load(raw)

    raw = state()
    raw["next_cluster_id"] = 0
    with pytest.raises(ValueError, match="conflicts"):
        load(raw)


def engine_config() -> dict[str, object]:
    return {
        "input": {"mode": "single"},
        "spell": {"tau_ratio": 0.5},
        "tokenizer": TOKENIZER,
        "header": HEADER,
        "output": {},
        "learning": LEARNING,
    }


def test_engine_load_is_atomic_on_any_failure(tmp_path: Path) -> None:
    engine = PinXieEngine.from_config_data(engine_config())
    engine.parser.process("existing model", line_id=9)
    original = engine.parser
    cache = tmp_path / "templates.json"
    cache.write_text(json.dumps({**state(), "next_cluster_id": 0}), encoding="utf-8")
    with pytest.raises(ValueError):
        engine.load_template_cache(tmp_path)
    assert engine.parser is original
    assert engine.parser.cluster_order == [0]


def test_unknown_fields_and_variable_names_are_rejected() -> None:
    raw = state()
    raw["unknown"] = True
    with pytest.raises(ValueError, match="root fields"):
        load(raw)
    raw = state()
    raw["clusters"][0]["variable_names"] = {}  # type: ignore[index]
    with pytest.raises(ValueError, match="cluster fields"):
        load(raw)
