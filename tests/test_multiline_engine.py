from __future__ import annotations

import json
from pathlib import Path

import pytest

from pin_xie import (
    DemoConfig,
    HeaderConfig,
    InputConfig,
    InputMode,
    OutputConfig,
    PinXieEngine,
    RunMode,
    SpellConfig,
    TokenizerConfig,
)


def build_config(tmp_path: Path, mode: InputMode) -> DemoConfig:
    multiline = mode is InputMode.MULTILINE
    return DemoConfig(
        input=InputConfig(mode=mode),
        spell=SpellConfig(),
        tokenizer=TokenizerConfig(use_jieba=False),
        header=HeaderConfig(
            parse_structure="<time> <level> <context>" if multiline else "<context>",
            strict_mode=multiline,
            field_patterns=(
                {"time": r"\d{4}-\d{2}-\d{2}", "level": r"INFO|ERROR"}
                if multiline
                else {}
            ),
        ),
        output=OutputConfig(dir=tmp_path / "output", show_tokens=True),
    )


def multiline_lines() -> list[str]:
    return [
        "2026-03-20 ERROR failed\n",
        "Traceback:\n",
        "  File app.py\n",
        "\n",
        "2026-03-21 INFO recovered\n",
    ]


def test_process_log_parses_multiline_and_process_line_delegates(tmp_path: Path) -> None:
    log = "2026-03-20 ERROR failed\n  detail"
    direct = PinXieEngine(build_config(tmp_path, InputMode.MULTILINE)).process_log(
        log, line_id=7, end_line_id=8
    )
    compatibility = PinXieEngine(
        build_config(tmp_path, InputMode.MULTILINE)
    ).process_line(log, line_id=7, end_line_id=8)

    assert direct == compatibility
    assert direct.context == "failed\n  detail"
    assert direct.log == log
    assert (direct.line_id, direct.end_line_id, direct.physical_line_count) == (7, 8, 2)


def test_process_log_validates_line_range(tmp_path: Path) -> None:
    engine = PinXieEngine(build_config(tmp_path, InputMode.SINGLE))
    with pytest.raises(ValueError, match="end_line_id"):
        engine.process_log("message", line_id=3, end_line_id=2)


def test_process_lines_uses_mode_specific_assembly(tmp_path: Path) -> None:
    single = PinXieEngine(build_config(tmp_path, InputMode.SINGLE))
    single_records = list(single.process_lines([" first  \n", "\n", "last\n"], start_line_id=4))
    assert [(r.log, r.line_id, r.end_line_id) for r in single_records] == [
        (" first  ", 4, 4),
        ("last", 6, 6),
    ]

    multiline = PinXieEngine(build_config(tmp_path, InputMode.MULTILINE))
    records = list(multiline.process_lines(multiline_lines()))
    assert [(r.line_id, r.end_line_id, r.physical_line_count) for r in records] == [
        (1, 4, 4),
        (5, 5, 1),
    ]
    assert records[0].context == "failed\nTraceback:\n  File app.py\n"


@pytest.mark.parametrize("mode", [RunMode.LEARN, RunMode.LEARN_PARSE, RunMode.PARSE])
def test_run_modes_share_boundaries_and_counts(
    tmp_path: Path, mode: RunMode
) -> None:
    config = build_config(tmp_path, InputMode.MULTILINE)
    log_path = tmp_path / "input.log"
    log_path.write_text("".join(multiline_lines()), encoding="utf-8")
    cache_dir = tmp_path / "cache"
    if mode is RunMode.PARSE:
        PinXieEngine(config).run_file(
            log_path, mode=RunMode.LEARN, template_dir=cache_dir
        )

    report = PinXieEngine(config).run_file(log_path, mode=mode, template_dir=cache_dir)

    assert report.processed_records == 2
    assert report.processed_physical_lines == 5
    assert not hasattr(report, "processed_lines")
    if mode is RunMode.LEARN:
        assert report.parsed_output_path is None
    else:
        assert report.parsed_output_path is not None
        payloads = [
            json.loads(line)
            for line in report.parsed_output_path.read_text(encoding="utf-8").splitlines()
        ]
        assert len(payloads) == 2
        assert payloads[0]["log"].endswith("  File app.py\n")
        assert payloads[0]["context"].endswith("  File app.py\n")
        assert payloads[0]["line_id"] == 1
        assert payloads[0]["end_line_id"] == 4
        assert payloads[0]["physical_line_count"] == 4


def test_run_file_counts_skipped_single_mode_blank_lines(tmp_path: Path) -> None:
    engine = PinXieEngine(build_config(tmp_path, InputMode.SINGLE))
    log_path = tmp_path / "single.log"
    log_path.write_text("one\n\n  \ntwo\n", encoding="utf-8")

    report = engine.run_file(
        log_path,
        mode=RunMode.LEARN,
        template_dir=tmp_path / "cache",
        write_parsed_output=False,
    )

    assert report.processed_records == 2
    assert report.processed_physical_lines == 4
    assert sum(cluster.size for cluster in engine.parser.all_clusters()) == 2


@pytest.mark.parametrize("mode", [RunMode.LEARN, RunMode.LEARN_PARSE])
def test_learning_modes_update_existing_template_cache(
    tmp_path: Path, mode: RunMode
) -> None:
    config = build_config(tmp_path, InputMode.SINGLE)
    cache_dir = tmp_path / "cache"
    first_log = tmp_path / "first.log"
    second_log = tmp_path / "second.log"
    first_log.write_text("alpha\n", encoding="utf-8")
    second_log.write_text("beta gamma delta\n", encoding="utf-8")

    PinXieEngine(config).run_file(
        first_log, mode=RunMode.LEARN, template_dir=cache_dir
    )
    updated = PinXieEngine(config)
    updated.run_file(second_log, mode=mode, template_dir=cache_dir)

    assert len(updated.parser.all_clusters()) == 2
    reloaded = PinXieEngine(config)
    reloaded.load_template_cache(cache_dir)
    assert len(reloaded.parser.all_clusters()) == 2


def test_template_cache_v2_saves_and_loads_complete_config(tmp_path: Path) -> None:
    config = build_config(tmp_path, InputMode.MULTILINE)
    engine = PinXieEngine(config)
    engine.process_log("2026-03-20 ERROR failed", line_id=1)
    cache_dir = tmp_path / "cache"

    cache_path = engine.save_template_cache(cache_dir)
    state = json.loads(cache_path.read_text(encoding="utf-8"))

    assert state["version"] == 2
    assert state["input"] == {"mode": "multiline"}
    assert state["header"] == {
        "parse_structure": "<time> <level> <context>",
        "strict_mode": True,
        "field_patterns": {
            "time": r"\d{4}-\d{2}-\d{2}",
            "level": r"INFO|ERROR",
        },
    }
    loaded = PinXieEngine(config)
    loaded.load_template_cache(cache_dir)
    assert len(loaded.parser.all_clusters()) == 1


@pytest.mark.parametrize(
    ("mutate", "difference"),
    [
        (lambda state: state["input"].update(mode="single"), "input.mode"),
        (
            lambda state: state["header"].update(parse_structure="<level> <context>"),
            "header.parse_structure",
        ),
        (lambda state: state["header"].update(strict_mode=False), "header.strict_mode"),
        (
            lambda state: state["header"].update(field_patterns={"level": "INFO"}),
            "header.field_patterns",
        ),
    ],
)
def test_template_cache_rejects_each_config_difference(
    tmp_path: Path, mutate: object, difference: str
) -> None:
    config = build_config(tmp_path, InputMode.MULTILINE)
    cache_dir = tmp_path / "cache"
    cache_path = PinXieEngine(config).save_template_cache(cache_dir)
    state = json.loads(cache_path.read_text(encoding="utf-8"))
    mutate(state)  # type: ignore[operator]
    cache_path.write_text(json.dumps(state), encoding="utf-8")

    engine = PinXieEngine(config)
    with pytest.raises(ValueError, match=rf"configuration mismatch.*{difference}"):
        engine.load_template_cache(cache_dir)
    assert engine.parser.all_clusters() == []


def test_template_cache_rejects_v1_without_partial_load(tmp_path: Path) -> None:
    config = build_config(tmp_path, InputMode.SINGLE)
    engine = PinXieEngine(config)
    original = engine.process_log("existing model", line_id=9).cluster_id
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "templates.json").write_text(
        json.dumps({"version": 1, "clusters": []}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match=r"version 1.*learn again"):
        engine.load_template_cache(cache_dir)
    assert [cluster.cluster_id for cluster in engine.parser.all_clusters()] == [original]


@pytest.mark.parametrize(
    "invalid_state",
    [
        [],
        {"version": 2, "input": [], "header": {}},
        {"version": 2, "input": {"mode": "single"}, "header": []},
    ],
)
def test_template_cache_structure_failure_does_not_replace_model(
    tmp_path: Path, invalid_state: object
) -> None:
    engine = PinXieEngine(build_config(tmp_path, InputMode.SINGLE))
    engine.process_log("existing model", line_id=1)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "templates.json").write_text(
        json.dumps(invalid_state), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="Invalid template cache"):
        engine.load_template_cache(cache_dir)
    assert len(engine.parser.all_clusters()) == 1
