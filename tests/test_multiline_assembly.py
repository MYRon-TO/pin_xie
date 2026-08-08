from __future__ import annotations

import pytest

from pin_xie import InputMode, RegexHeaderParser
from pin_xie.multiline import LogAssemblyError, LogicalLog, LogRecordAssembler


def multiline_assembler() -> LogRecordAssembler:
    parser = RegexHeaderParser(
        parse_structure="<time> <level> <context>",
        field_patterns={
            "time": r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}",
            "level": r"INFO|ERROR",
        },
    )
    return LogRecordAssembler(InputMode.MULTILINE, parser)


def test_single_assembles_nonblank_lines_and_preserves_whitespace() -> None:
    assembler = LogRecordAssembler(InputMode.SINGLE)

    records = list(
        assembler.assemble([" first  \r\n", "\n", " \t\r", "last\r"], start_line=4)
    )

    assert records == [
        LogicalLog(text=" first  ", start_line=4, end_line=4),
        LogicalLog(text="last", start_line=7, end_line=7),
    ]
    assert records[0].physical_line_count == 1
    assert assembler.flush() is None


def test_single_empty_input_is_empty() -> None:
    assert list(LogRecordAssembler(InputMode.SINGLE).assemble([])) == []


def test_multiline_splits_logs_and_preserves_blank_lines_and_indentation() -> None:
    assembler = multiline_assembler()
    lines = [
        "2026-03-20 10:00:00 ERROR failed\r\n",
        "Traceback:\n",
        "  File app.py  \r\n",
        "\r\n",
        "2026-03-20 10:00:01 INFO recovered\n",
    ]

    records = list(assembler.assemble(lines))

    assert records == [
        LogicalLog(
            text=(
                "2026-03-20 10:00:00 ERROR failed\n"
                "Traceback:\n"
                "  File app.py  \n"
            ),
            start_line=1,
            end_line=4,
        ),
        LogicalLog(
            text="2026-03-20 10:00:01 INFO recovered",
            start_line=5,
            end_line=5,
        ),
    ]
    assert records[0].physical_line_count == 4


def test_multiline_single_header_and_header_only_can_be_flushed() -> None:
    assembler = multiline_assembler()

    assert assembler.feed("2026-03-20 10:00:00 INFO \n", 8) is None
    assert assembler.feed("detail\n", 9) is None
    assert assembler.flush() == LogicalLog(
        text="2026-03-20 10:00:00 INFO \ndetail",
        start_line=8,
        end_line=9,
    )
    assert assembler.flush() is None


def test_multiline_rejects_text_or_blank_before_first_header() -> None:
    for raw_line in ("orphan text\n", "  \r\n"):
        assembler = multiline_assembler()
        with pytest.raises(LogAssemblyError) as error:
            assembler.feed(raw_line, 12)

        assert error.value.line_number == 12
        assert error.value.line_preview == raw_line.rstrip("\r\n").replace("\t", "\\t")
        assert "12" in str(error.value)


def test_matching_body_line_starts_record_and_damaged_header_is_continuation() -> None:
    assembler = multiline_assembler()
    lines = [
        "2026-03-20 10:00:00 INFO first\n",
        "2026-03-20 10:00:01 WARN damaged\n",
        "2026-03-20 10:00:02 ERROR second\n",
    ]

    assert list(assembler.assemble(lines)) == [
        LogicalLog(
            text=(
                "2026-03-20 10:00:00 INFO first\n"
                "2026-03-20 10:00:01 WARN damaged"
            ),
            start_line=1,
            end_line=2,
        ),
        LogicalLog(
            text="2026-03-20 10:00:02 ERROR second",
            start_line=3,
            end_line=3,
        ),
    ]


def test_feed_in_batches_matches_assemble() -> None:
    lines = [
        "2026-03-20 10:00:00 INFO first\n",
        "continued\n",
        "2026-03-20 10:00:01 ERROR second",
    ]
    expected = list(multiline_assembler().assemble(lines, start_line=20))
    streamed = multiline_assembler()
    actual = []
    for line_number, line in enumerate(lines, start=20):
        record = streamed.feed(line, line_number)
        if record is not None:
            actual.append(record)
    final = streamed.flush()
    if final is not None:
        actual.append(final)

    assert actual == expected


def test_error_preview_is_bounded() -> None:
    assembler = multiline_assembler()
    with pytest.raises(LogAssemblyError) as error:
        assembler.feed("x" * 200, 1)

    assert len(error.value.line_preview) == 80
    assert error.value.line_preview.endswith("...")
