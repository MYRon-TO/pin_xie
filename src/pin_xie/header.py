from __future__ import annotations

from dataclasses import dataclass

import regex


CONTEXT_ONLY_STRUCTURE = "<context>"
PLACEHOLDER_RE = regex.compile(r"<([A-Za-z_][A-Za-z0-9_]*)>")


@dataclass
class HeaderParseResult:
    matched: bool
    context: str
    fields: dict[str, str]


class RegexHeaderParser:
    def __init__(
        self,
        parse_structure: str = CONTEXT_ONLY_STRUCTURE,
        field_patterns: dict[str, str] | None = None,
        strict_mode: bool = False,
    ) -> None:
        if "<context>" not in parse_structure:
            raise ValueError("parse_structure must contain '<context>'")

        self.parse_structure = parse_structure
        self.field_patterns = dict(field_patterns or {})
        self.strict_mode = strict_mode
        self.header_re, self.fields_in_structure = self._compile_structure(
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

    @classmethod
    def _compile_structure(
        cls,
        parse_structure: str,
        field_patterns: dict[str, str],
    ) -> tuple[regex.Pattern[str], tuple[str, ...]]:
        regex_parts: list[str] = [r"^\s*"]
        field_names: list[str] = []
        cursor = 0

        for match in PLACEHOLDER_RE.finditer(parse_structure):
            literal = parse_structure[cursor : match.start()]
            regex_parts.append(cls._literal_to_regex(literal))

            field_name = match.group(1)
            if field_name in field_names:
                raise ValueError(
                    f"Duplicate placeholder in parse_structure: <{field_name}>"
                )

            field_pattern = field_patterns.get(field_name)
            if not field_pattern:
                if field_name == "context":
                    field_pattern = r".*"
                else:
                    raise ValueError(
                        f"Missing regex pattern for placeholder <{field_name}>"
                    )

            regex_parts.append(f"(?P<{field_name}>{field_pattern})")
            field_names.append(field_name)
            cursor = match.end()

        regex_parts.append(cls._literal_to_regex(parse_structure[cursor:]))
        regex_parts.append(r"\s*$")

        if "context" not in field_names:
            raise ValueError("parse_structure must contain '<context>'")

        return regex.compile("".join(regex_parts)), tuple(field_names)

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
