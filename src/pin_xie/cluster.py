from __future__ import annotations

from dataclasses import dataclass, field

from .template import TemplateToken, variable_count


@dataclass
class LCSObject:
    cluster_id: int
    template_tokens: list[TemplateToken]
    line_ids: list[int] = field(default_factory=list)
    size: int = 0
    token_set: set[str] = field(default_factory=set)
    variable_names: dict[int, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.size == 0:
            self.size = len(self.line_ids)
        if not self.token_set:
            self.token_set = {
                token for token in self.template_tokens if token is not None
            }
        self._prune_variable_names()

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
        self.token_set = {token for token in new_template_tokens if token is not None}
        self._prune_variable_names()

    def set_variable_name(self, var_index: int, var_name: str | None) -> None:
        if var_index < 0 or var_index >= self.variable_token_count:
            raise IndexError(
                f"Variable index out of range: {var_index}. "
                f"Valid range: [0, {self.variable_token_count - 1}]"
            )

        if var_name is None:
            self.variable_names.pop(var_index, None)
            return

        normalized_name = var_name.strip()
        if not normalized_name:
            self.variable_names.pop(var_index, None)
            return

        for existing_index, existing_name in self.variable_names.items():
            if existing_index != var_index and existing_name == normalized_name:
                raise ValueError(
                    f"Duplicate variable name in template {self.cluster_id}: "
                    f"{normalized_name!r}"
                )

        self.variable_names[var_index] = normalized_name

    def _prune_variable_names(self) -> None:
        max_count = self.variable_token_count
        self.variable_names = {
            index: name
            for index, name in self.variable_names.items()
            if 0 <= index < max_count and name.strip()
        }


def create_cluster(cluster_id: int, tokens: list[str], line_id: int) -> LCSObject:
    return LCSObject(
        cluster_id=cluster_id,
        template_tokens=list(tokens),
        line_ids=[line_id],
        size=1,
        token_set=set(tokens),
        variable_names={},
    )
