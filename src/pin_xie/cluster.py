from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace

from .models import InputToken, LiteralTemplateToken, TemplateToken
from .template import variable_count


@dataclass
class LCSObject:
    cluster_id: int
    template_tokens: list[TemplateToken]
    line_ids: list[int] = field(default_factory=list)
    size: int = 0
    token_set: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        if self.size == 0:
            self.size = len(self.line_ids)
        if not self.token_set:
            self._refresh_token_set()
        self._validate_variable_names()

    @property
    def constant_token_count(self) -> int:
        return len(self.token_set)

    @property
    def variable_token_count(self) -> int:
        return variable_count(self.template_tokens)

    def add_line(self, line_id: int) -> None:
        self.line_ids.append(line_id)
        self.size += 1

    def update_template(self, new_template_tokens: list[TemplateToken]) -> None:
        self.template_tokens = new_template_tokens
        self._refresh_token_set()
        self._validate_variable_names()

    def get_variable_names(self) -> dict[int, str]:
        return {
            index: token.var_name for index, token in enumerate(self._variable_tokens())
        }

    def set_variable_name(self, var_index: int, var_name: str | None) -> None:
        self.replace_variable_names({var_index: var_name})

    def replace_variable_names(self, mapping: Mapping[int, str | None]) -> None:
        variables = self._variable_tokens()
        replacements: dict[int, str] = {}
        reset_indices: list[int] = []

        for raw_index, raw_name in mapping.items():
            index = int(raw_index)
            if index < 0 or index >= len(variables):
                message = (
                    f"Variable index out of range: {index}. Valid range: "
                    f"[0, {len(variables) - 1}]"
                )
                raise IndexError(message)
            normalized = None if raw_name is None else raw_name.strip()
            if not normalized:
                reset_indices.append(index)
            else:
                replacements[index] = normalized

        final_names = [token.var_name for token in variables]
        for index, name in replacements.items():
            final_names[index] = name

        used_names = {
            name for index, name in enumerate(final_names) if index not in reset_indices
        }
        for index in reset_indices:
            default_index = 0
            while f"var_{default_index}" in used_names:
                default_index += 1
            final_names[index] = f"var_{default_index}"
            used_names.add(final_names[index])

        if any(not name for name in final_names) or len(set(final_names)) != len(
            final_names
        ):
            raise ValueError(
                f"Variable names must be non-empty and unique in template {self.cluster_id}"
            )

        replacement_iter = iter(final_names)
        self.template_tokens = [
            replace(token, var_name=next(replacement_iter))
            if token.kind == "variable"
            else token
            for token in self.template_tokens
        ]

    def _variable_tokens(self):
        return [token for token in self.template_tokens if token.kind == "variable"]

    def _refresh_token_set(self) -> None:
        self.token_set = {
            token.text for token in self.template_tokens if token.kind == "literal"
        }

    def _validate_variable_names(self) -> None:
        names = [token.var_name for token in self._variable_tokens()]
        if any(not name.strip() for name in names) or len(set(names)) != len(names):
            raise ValueError(
                f"Variable names must be non-empty and unique in template {self.cluster_id}"
            )


def create_cluster(
    cluster_id: int, tokens: list[InputToken], line_id: int
) -> LCSObject:
    template_tokens: list[TemplateToken] = [
        LiteralTemplateToken(text=token.text, sources=(token.source,))
        for token in tokens
    ]
    return LCSObject(
        cluster_id=cluster_id,
        template_tokens=template_tokens,
        line_ids=[line_id],
        size=1,
        token_set={token.text for token in tokens},
    )
