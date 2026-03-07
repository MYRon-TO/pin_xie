from __future__ import annotations

from dataclasses import dataclass, field


WILDCARD = "*"


@dataclass
class LCSObject:
    cluster_id: int
    template_tokens: list[str]
    line_ids: list[int] = field(default_factory=list)
    size: int = 0
    token_set: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        if self.size == 0:
            self.size = len(self.line_ids)
        if not self.token_set:
            self.token_set = {
                token for token in self.template_tokens if token != WILDCARD
            }

    @property
    def constant_token_count(self) -> int:
        return len(self.token_set)

    def add_line(self, line_id: int) -> None:
        self.line_ids.append(line_id)
        self.size += 1

    def update_template(self, new_template_tokens: list[str]) -> None:
        self.template_tokens = new_template_tokens
        self.token_set = {token for token in new_template_tokens if token != WILDCARD}


def create_cluster(cluster_id: int, tokens: list[str], line_id: int) -> LCSObject:
    return LCSObject(
        cluster_id=cluster_id,
        template_tokens=list(tokens),
        line_ids=[line_id],
        size=1,
        token_set=set(tokens),
    )
