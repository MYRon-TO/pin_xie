from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from .config import InputMode
from .header import RegexHeaderParser


@dataclass(frozen=True)
class LogicalLog:
    text: str
    start_line: int
    end_line: int

    @property
    def physical_line_count(self) -> int:
        return self.end_line - self.start_line + 1


class LogAssemblyError(ValueError):
    def __init__(self, line_number: int, line_preview: str) -> None:
        self.line_number = line_number
        self.line_preview = line_preview
        super().__init__(
            f"Physical line {line_number} appears before the first log header: "
            f"{line_preview!r}"
        )


class LogRecordAssembler:
    def __init__(
        self,
        mode: InputMode,
        header_parser: RegexHeaderParser | None = None,
    ) -> None:
        if mode is InputMode.MULTILINE and header_parser is None:
            raise ValueError("header_parser is required in multiline mode")
        self.mode = mode
        self.header_parser = header_parser
        self._buffer: list[str] = []
        self._start_line: int | None = None
        self._end_line: int | None = None

    @staticmethod
    def _remove_line_terminator(raw_line: str) -> str:
        if raw_line.endswith("\r\n"):
            return raw_line[:-2]
        if raw_line.endswith(("\n", "\r")):
            return raw_line[:-1]
        return raw_line

    @staticmethod
    def _preview(line: str, limit: int = 80) -> str:
        escaped = (
            line.replace("\\", "\\\\")
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
        )
        if len(escaped) <= limit:
            return escaped
        return f"{escaped[: limit - 3]}..."

    def feed(self, raw_line: str, line_number: int) -> LogicalLog | None:
        line = self._remove_line_terminator(raw_line)

        if self.mode is InputMode.SINGLE:
            if line.strip() == "":
                return None
            return LogicalLog(text=line, start_line=line_number, end_line=line_number)

        assert self.header_parser is not None
        if self.header_parser.is_header_line(line):
            completed = self.flush()
            self._buffer = [line]
            self._start_line = line_number
            self._end_line = line_number
            return completed

        if not self._buffer:
            raise LogAssemblyError(line_number, self._preview(line))

        self._buffer.append(line)
        self._end_line = line_number
        return None

    def flush(self) -> LogicalLog | None:
        if not self._buffer:
            return None

        assert self._start_line is not None
        assert self._end_line is not None
        logical_log = LogicalLog(
            text="\n".join(self._buffer),
            start_line=self._start_line,
            end_line=self._end_line,
        )
        self._buffer = []
        self._start_line = None
        self._end_line = None
        return logical_log

    def assemble(
        self,
        lines: Iterable[str],
        *,
        start_line: int = 1,
    ) -> Iterator[LogicalLog]:
        for line_number, raw_line in enumerate(lines, start=start_line):
            completed = self.feed(raw_line, line_number)
            if completed is not None:
                yield completed

        completed = self.flush()
        if completed is not None:
            yield completed
