# pyright: standard

from __future__ import annotations

import json
from pathlib import Path

from pin_xie import (
    DemoConfig,
    HeaderConfig,
    InputConfig,
    InputMode,
    LiteralTemplateToken,
    MaskPattern,
    OutputConfig,
    PinXieEngine,
    RunMode,
    SpellConfig,
    TokenizerConfig,
    VariableTemplateToken,
)


def build_config(tmp_path: Path) -> DemoConfig:
    return DemoConfig(
        input=InputConfig(mode=InputMode.SINGLE),
        spell=SpellConfig(tau_ratio=0.2),
        tokenizer=TokenizerConfig(
            use_jieba=False,
            mask_patterns=(
                MaskPattern("ipv4", r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
                MaskPattern("number", r"\b\d+\b"),
            ),
        ),
        header=HeaderConfig(parse_structure="<context>"),
        output=OutputConfig(dir=tmp_path / "output", show_tokens=True),
    )


def test_rich_template_cache_parse_and_outputs_end_to_end(tmp_path: Path) -> None:
    config = build_config(tmp_path)
    cache_dir = tmp_path / "cache"
    training = tmp_path / "training.log"
    training.write_text(
        "connect 10.0.0.1 port 80 ok\nconnect client-a port service ok\n",
        encoding="utf-8",
    )

    learner = PinXieEngine(config)
    learner.run_file(training, mode=RunMode.LEARN, template_dir=cache_dir)
    cluster = learner.parser.all_clusters()[0]
    learner.set_template_variable_names(
        cluster.cluster_id, {0: "client", 1: "service_port"}
    )
    learner.save_template_cache(cache_dir)

    variables = [
        token
        for token in cluster.template_tokens
        if isinstance(token, VariableTemplateToken)
    ]
    assert [token.var_name for token in variables] == ["client", "service_port"]
    assert [source.kind for source in variables[0].sources] == ["plain", "regex"]
    assert [source.kind for source in variables[1].sources] == ["plain", "regex"]
    literals = [
        token
        for token in cluster.template_tokens
        if isinstance(token, LiteralTemplateToken)
    ]
    assert [token.text for token in literals] == ["connect", "port", "ok"]
    assert all(
        [source.kind for source in token.sources] == ["plain"] for token in literals
    )

    new_log = "connect 10.0.0.9 port 8080 ok"
    before = learner.process_log(new_log, line_id=10, update_model=False)
    cached = json.loads((cache_dir / "templates.json").read_text(encoding="utf-8"))
    assert cached["version"] == 4
    assert cached["tokenizer"]["mask_patterns"] == [
        {"name": "ipv4", "pattern": r"\b(?:\d{1,3}\.){3}\d{1,3}\b"},
        {"name": "number", "pattern": r"\b\d+\b"},
    ]
    assert "variable_names" not in json.dumps(cached)

    inference = tmp_path / "inference.log"
    inference.write_text(new_log + "\n", encoding="utf-8")
    loaded = PinXieEngine(config)
    report = loaded.run_file(
        inference,
        mode=RunMode.PARSE,
        template_dir=cache_dir,
        write_template_summary=True,
    )
    after = loaded.process_log(new_log, line_id=10, update_model=False)
    assert (after.cluster_id, after.template, after.template_tokens) == (
        before.cluster_id,
        before.template,
        before.template_tokens,
    )
    assert after.parameters == before.parameters
    assert [parameter.var_name for parameter in after.parameters] == [
        "client",
        "service_port",
    ]
    assert [parameter.value for parameter in after.parameters] == ["10.0.0.9", "8080"]
    assert [
        [source.mask_name for source in parameter.sources if source.kind == "regex"]
        for parameter in after.parameters
    ] == [
        ["ipv4"],
        ["number"],
    ]

    assert report.processed_records == 1
    assert report.parsed_output_path is not None
    payload = json.loads(report.parsed_output_path.read_text(encoding="utf-8"))
    assert "named_parameters" not in payload
    assert "variable_names" not in payload
    assert isinstance(payload["template_tokens"], list)
    assert isinstance(payload["parameters"], list)
    assert isinstance(payload["tokens"], list)
    assert payload["template_tokens"] == [
        {"kind": "literal", "text": "connect", "sources": [{"kind": "plain"}]},
        {
            "kind": "variable",
            "var_name": "client",
            "sources": [
                {"kind": "plain"},
                {"kind": "regex", "mask_name": "ipv4"},
            ],
        },
        {"kind": "literal", "text": "port", "sources": [{"kind": "plain"}]},
        {
            "kind": "variable",
            "var_name": "service_port",
            "sources": [
                {"kind": "plain"},
                {"kind": "regex", "mask_name": "number"},
            ],
        },
        {"kind": "literal", "text": "ok", "sources": [{"kind": "plain"}]},
    ]
    assert payload["parameters"][0]["sources"] == [
        {"kind": "regex", "mask_name": "ipv4"}
    ]
    assert payload["parameters"][1]["sources"] == [
        {"kind": "regex", "mask_name": "number"}
    ]
    assert report.template_output_path is not None
    summary = report.template_output_path.read_text(encoding="utf-8")
    assert "client" in summary and "service_port" in summary
