from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import regex


CONTEXT_ONLY_STRUCTURE = "<context>"
PLACEHOLDER_RE = regex.compile(r"<([A-Za-z_][A-Za-z0-9_]*)>")


@dataclass
class HeaderParseResult:
    matched: bool
    context: str
    fields: dict[str, str]


@dataclass(frozen=True)
class HeaderValidationIssue:
    stage: str
    reason: str
    message: str
    field: str | None = None
    pattern: str | None = None
    structure_part: str | None = None


@dataclass(frozen=True)
class _StructureNode:
    kind: str
    literal: str | None = None
    field: str | None = None
    literal_re: regex.Pattern[str] | None = None


@dataclass(frozen=True)
class _FailurePoint:
    kind: str
    node_index: int
    pos: int


class HeaderConfigurationError(ValueError):
    def __init__(self, issue: HeaderValidationIssue) -> None:
        super().__init__(issue.message)
        self.issue = issue


class RegexHeaderParser:
    def __init__(
        self,
        parse_structure: str = CONTEXT_ONLY_STRUCTURE,
        field_patterns: dict[str, str] | None = None,
        strict_mode: bool = False,
    ) -> None:
        if "<context>" not in parse_structure:
            raise HeaderConfigurationError(
                HeaderValidationIssue(
                    stage="config",
                    reason="parse_structure_missing_context",
                    message="header.parse_structure must contain '<context>'",
                )
            )

        self.parse_structure = parse_structure
        self.field_patterns = dict(field_patterns or {})
        self.strict_mode = strict_mode
        (
            self.nodes,
            self.fields_in_structure,
            self._compiled_field_patterns,
        ) = self._build_structure_nodes(
            parse_structure=parse_structure,
            field_patterns=self.field_patterns,
        )
        self.header_re = self._compile_structure(
            parse_structure=parse_structure,
            field_patterns=self.field_patterns,
        )

    @staticmethod
    def _literal_to_regex(literal: str) -> str:
        if not literal:
            return ""

        out: list[str] = []
        idx = 0
        while idx < len(literal):
            if literal[idx].isspace():
                while idx < len(literal) and literal[idx].isspace():
                    idx += 1
                out.append(r"\s*")
            else:
                out.append(regex.escape(literal[idx]))
                idx += 1

        return "".join(out)

    @staticmethod
    def _preview(value: str, limit: int = 80) -> str:
        escaped = (
            value.replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
            .replace("'", "\\'")
        )
        if len(escaped) <= limit:
            return escaped
        return f"{escaped[: max(0, limit - 3)]}..."

    @staticmethod
    def _limit_message(message: str, limit: int = 500) -> str:
        if len(message) <= limit:
            return message
        return f"{message[: max(0, limit - 3)]}..."

    @classmethod
    def _build_trace(cls, entries: list[str]) -> str:
        return cls._limit_message(f"trace: {'; '.join(entries)}")

    @classmethod
    def _build_structure_nodes(
        cls,
        parse_structure: str,
        field_patterns: dict[str, str],
    ) -> tuple[list[_StructureNode], tuple[str, ...], dict[str, regex.Pattern[str]]]:
        nodes: list[_StructureNode] = []
        field_names: list[str] = []
        compiled_field_patterns: dict[str, regex.Pattern[str]] = {}
        cursor = 0

        for match in PLACEHOLDER_RE.finditer(parse_structure):
            literal = parse_structure[cursor : match.start()]
            if literal:
                nodes.append(
                    _StructureNode(
                        kind="literal",
                        literal=literal,
                        literal_re=regex.compile(cls._literal_to_regex(literal)),
                    )
                )

            field_name = match.group(1)
            if field_name in field_names:
                raise HeaderConfigurationError(
                    HeaderValidationIssue(
                        stage="config",
                        reason="parse_structure_duplicate_placeholder",
                        message=(
                            "Duplicate placeholder in header.parse_structure: "
                            f"<{field_name}>"
                        ),
                    )
                )

            if field_name != "context":
                field_pattern = field_patterns.get(field_name)
                if not field_pattern:
                    raise HeaderConfigurationError(
                        HeaderValidationIssue(
                            stage="config",
                            reason="field_pattern_missing",
                            message=(
                                "Missing regex pattern for placeholder "
                                f"<{field_name}> in header.field_patterns"
                            ),
                            field=field_name,
                        )
                    )

                try:
                    compiled_field_patterns[field_name] = regex.compile(
                        f"(?:{field_pattern})"
                    )
                except regex.error as exc:
                    raise HeaderConfigurationError(
                        HeaderValidationIssue(
                            stage="config",
                            reason="field_pattern_invalid_regex",
                            message=(
                                f"Invalid regex in header.field_patterns.{field_name}: "
                                f"{exc}"
                            ),
                            field=field_name,
                            pattern=field_pattern,
                        )
                    ) from exc

            nodes.append(_StructureNode(kind="field", field=field_name))
            field_names.append(field_name)
            cursor = match.end()

        trailing_literal = parse_structure[cursor:]
        if trailing_literal:
            nodes.append(
                _StructureNode(
                    kind="literal",
                    literal=trailing_literal,
                    literal_re=regex.compile(cls._literal_to_regex(trailing_literal)),
                )
            )

        if "context" not in field_names:
            raise HeaderConfigurationError(
                HeaderValidationIssue(
                    stage="config",
                    reason="parse_structure_missing_context",
                    message="header.parse_structure must contain '<context>'",
                )
            )

        return nodes, tuple(field_names), compiled_field_patterns

    @classmethod
    def _compile_structure(
        cls,
        parse_structure: str,
        field_patterns: dict[str, str],
    ) -> regex.Pattern[str]:
        regex_parts: list[str] = [r"^\s*"]
        cursor = 0

        for match in PLACEHOLDER_RE.finditer(parse_structure):
            literal = parse_structure[cursor : match.start()]
            regex_parts.append(cls._literal_to_regex(literal))

            field_name = match.group(1)
            field_pattern = field_patterns.get(field_name)
            if not field_pattern:
                if field_name == "context":
                    field_pattern = r".*"
                else:
                    raise HeaderConfigurationError(
                        HeaderValidationIssue(
                            stage="config",
                            reason="field_pattern_missing",
                            message=(
                                "Missing regex pattern for placeholder "
                                f"<{field_name}> in header.field_patterns"
                            ),
                            field=field_name,
                        )
                    )

            regex_parts.append(f"(?P<{field_name}>{field_pattern})")
            cursor = match.end()

        regex_parts.append(cls._literal_to_regex(parse_structure[cursor:]))
        regex_parts.append(r"\s*$")

        try:
            return regex.compile("".join(regex_parts))
        except regex.error as exc:
            raise HeaderConfigurationError(
                HeaderValidationIssue(
                    stage="config",
                    reason="parse_structure_invalid_regex",
                    message=(
                        f"Invalid header.parse_structure regex composition: {exc}"
                    ),
                )
            ) from exc

    def _structure_part(self, failure: _FailurePoint) -> str:
        if failure.kind == "end":
            return "end"

        previous_field: str | None = None
        next_field: str | None = None

        for node_index in range(failure.node_index - 1, -1, -1):
            node = self.nodes[node_index]
            if node.kind == "field":
                previous_field = node.field
                break

        for node_index in range(failure.node_index + 1, len(self.nodes)):
            node = self.nodes[node_index]
            if node.kind == "field":
                next_field = node.field
                break

        if previous_field is None:
            return "start"
        if next_field is None:
            return f"after <{previous_field}>"
        return f"between <{previous_field}> and <{next_field}>"

    def _structure_failure_literal_preview(self, failure: _FailurePoint) -> str:
        if failure.kind == "end":
            return "<END>"

        node = self.nodes[failure.node_index]
        return self._preview(node.literal or "")

    def _structure_match(
        self, sample: str
    ) -> tuple[dict[str, str], _FailurePoint | None]:
        @lru_cache(maxsize=None)
        def can_match(node_index: int, pos: int) -> bool:
            if node_index == len(self.nodes):
                return pos == len(sample)

            node = self.nodes[node_index]
            if node.kind == "literal":
                literal_re = node.literal_re
                assert literal_re is not None
                match = literal_re.match(sample, pos)
                return match is not None and can_match(node_index + 1, match.end())

            for end in range(pos, len(sample) + 1):
                if can_match(node_index + 1, end):
                    return True

            return False

        @lru_cache(maxsize=None)
        def first_failure(node_index: int, pos: int) -> _FailurePoint | None:
            if node_index == len(self.nodes):
                if pos == len(sample):
                    return None
                return _FailurePoint(kind="end", node_index=node_index, pos=pos)

            node = self.nodes[node_index]
            if node.kind == "literal":
                literal_re = node.literal_re
                assert literal_re is not None
                match = literal_re.match(sample, pos)
                if match is None:
                    return _FailurePoint(kind="literal", node_index=node_index, pos=pos)
                return first_failure(node_index + 1, match.end())

            best_failure: _FailurePoint | None = None
            for end in range(pos, len(sample) + 1):
                failure = first_failure(node_index + 1, end)
                if failure is None:
                    return None
                if best_failure is None or (
                    failure.node_index,
                    failure.pos,
                ) < (
                    best_failure.node_index,
                    best_failure.pos,
                ):
                    best_failure = failure

            return best_failure

        def collect_success(
            node_index: int, pos: int, values: dict[str, str]
        ) -> dict[str, str]:
            if node_index == len(self.nodes):
                return values

            node = self.nodes[node_index]
            if node.kind == "literal":
                literal_re = node.literal_re
                assert literal_re is not None
                match = literal_re.match(sample, pos)
                if match is None:
                    return values
                return collect_success(node_index + 1, match.end(), values)

            field_name = node.field
            assert field_name is not None
            boundary_end: int | None = None
            exact_match_end: int | None = None
            preferred_end: int | None = None
            fallback_end: int | None = None
            next_node = (
                self.nodes[node_index + 1] if node_index + 1 < len(self.nodes) else None
            )
            for end in range(pos, len(sample) + 1):
                if can_match(node_index + 1, end):
                    raw_value = sample[pos:end]
                    candidate_value = raw_value.strip()
                    if fallback_end is None:
                        fallback_end = end
                    if next_node is not None and next_node.kind == "literal":
                        literal_re = next_node.literal_re
                        assert literal_re is not None
                        literal_match = literal_re.match(sample, end)
                        if (
                            boundary_end is None
                            and literal_match is not None
                            and literal_match.end() > end
                        ):
                            boundary_end = end
                    if field_name == "context":
                        preferred_end = end
                        break
                    if self._field_matches(field_name, candidate_value):
                        if raw_value == candidate_value:
                            exact_match_end = end
                            break
                        if preferred_end is None:
                            preferred_end = end

            chosen_end = exact_match_end
            if chosen_end is None:
                chosen_end = (
                    preferred_end if preferred_end is not None else fallback_end
                )
            if chosen_end == fallback_end and boundary_end is not None:
                chosen_end = boundary_end
            if chosen_end is not None:
                values[field_name] = sample[pos:chosen_end].strip()
                return collect_success(node_index + 1, chosen_end, values)

            return values

        def collect_until_failure(
            node_index: int,
            pos: int,
            target: _FailurePoint,
            values: dict[str, str],
        ) -> dict[str, str]:
            if node_index == len(self.nodes):
                return values

            if node_index == target.node_index and target.kind == "literal":
                return values

            node = self.nodes[node_index]
            if node.kind == "literal":
                literal_re = node.literal_re
                assert literal_re is not None
                match = literal_re.match(sample, pos)
                if match is None:
                    return values
                return collect_until_failure(
                    node_index + 1, match.end(), target, values
                )

            field_name = node.field
            assert field_name is not None
            boundary_end: int | None = None
            exact_match_end: int | None = None
            preferred_end: int | None = None
            fallback_end: int | None = None
            next_node = (
                self.nodes[node_index + 1] if node_index + 1 < len(self.nodes) else None
            )
            for end in range(pos, len(sample) + 1):
                if first_failure(node_index + 1, end) == target:
                    raw_value = sample[pos:end]
                    candidate_value = raw_value.strip()
                    if fallback_end is None:
                        fallback_end = end
                    if next_node is not None and next_node.kind == "literal":
                        literal_re = next_node.literal_re
                        assert literal_re is not None
                        literal_match = literal_re.match(sample, end)
                        if (
                            boundary_end is None
                            and literal_match is not None
                            and literal_match.end() > end
                        ):
                            boundary_end = end
                    if field_name == "context":
                        preferred_end = end
                        break
                    if self._field_matches(field_name, candidate_value):
                        if raw_value == candidate_value:
                            exact_match_end = end
                            break
                        if preferred_end is None:
                            preferred_end = end

            chosen_end = exact_match_end
            if chosen_end is None:
                chosen_end = (
                    preferred_end if preferred_end is not None else fallback_end
                )
            if chosen_end == fallback_end and boundary_end is not None:
                chosen_end = boundary_end
            if chosen_end is not None:
                values[field_name] = sample[pos:chosen_end].strip()
                return collect_until_failure(node_index + 1, chosen_end, target, values)

            return values

        if can_match(0, 0):
            return collect_success(0, 0, {}), None

        failure = first_failure(0, 0)
        if failure is None:
            return {}, None

        return collect_until_failure(0, 0, failure, {}), failure

    def _field_matches(self, field_name: str, value: str) -> bool:
        return self._compiled_field_patterns[field_name].fullmatch(value) is not None

    def _successful_trace_entries(self, values: dict[str, str]) -> list[str]:
        entries: list[str] = []

        for field_name in self.fields_in_structure:
            if field_name == "context" or field_name not in values:
                continue
            if not self._field_matches(field_name, values[field_name]):
                continue
            entries.append(
                f"<{field_name}>[OK] pattern='{self._preview(self.field_patterns[field_name])}' "
                f"value='{self._preview(values[field_name])}'"
            )

        return entries

    def validate_sample(self, sample: str) -> HeaderValidationIssue | None:
        values, structure_failure = self._structure_match(sample)
        if structure_failure is not None:
            trace_entries = self._successful_trace_entries(values)
            trace_entries.append(
                f"[FAIL] literal='{self._structure_failure_literal_preview(structure_failure)}'"
            )
            message = self._limit_message(
                "Sample does not match header.parse_structure at "
                f"{self._structure_part(structure_failure)}; {self._build_trace(trace_entries)}"
            )
            return HeaderValidationIssue(
                stage="sample",
                reason="parse_structure_mismatch",
                message=message,
                structure_part=self._structure_part(structure_failure),
            )

        trace_entries: list[str] = []
        for field_name in self.fields_in_structure:
            if field_name == "context" or field_name not in values:
                continue

            value = values[field_name]
            pattern = self.field_patterns[field_name]
            if self._field_matches(field_name, value):
                trace_entries.append(
                    f"<{field_name}>[OK] pattern='{self._preview(pattern)}' "
                    f"value='{self._preview(value)}'"
                )
                continue

            trace_entries.append(
                f"<{field_name}>[FAIL] pattern='{self._preview(pattern)}' "
                f"value='{self._preview(value)}'"
            )
            message = self._limit_message(
                "Field "
                f"<{field_name}> does not match header.field_patterns.{field_name}: "
                f"value={self._preview(value)}; {self._build_trace(trace_entries)}"
            )
            return HeaderValidationIssue(
                stage="sample",
                reason="field_pattern_mismatch",
                message=message,
                field=field_name,
                pattern=pattern,
            )

        return None

    def parse(self, log: str) -> HeaderParseResult:
        match = self.header_re.match(log)
        if match is None:
            if self.strict_mode:
                raise ValueError(
                    "Log line does not match parse_structure: "
                    f"{self.parse_structure} | log={log!r}"
                )

            return HeaderParseResult(
                matched=False,
                context=log.strip(),
                fields={},
            )

        parsed_fields: dict[str, str] = {}
        for field_name in self.fields_in_structure:
            value = match.group(field_name)
            parsed_fields[field_name] = value.strip() if value is not None else ""

        context = parsed_fields.get("context", "").strip()

        return HeaderParseResult(
            matched=True,
            context=context,
            fields=parsed_fields,
        )
