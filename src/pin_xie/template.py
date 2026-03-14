from __future__ import annotations

from collections.abc import Mapping


TemplateToken = str | None


def is_variable_token(token: TemplateToken) -> bool:
    return token is None


def _append_variable_slot(tokens: list[TemplateToken]) -> None:
    if not tokens or tokens[-1] is not None:
        tokens.append(None)


def compress_variable_slots(tokens: list[TemplateToken]) -> list[TemplateToken]:
    merged: list[TemplateToken] = []
    for token in tokens:
        if token is None:
            _append_variable_slot(merged)
        else:
            merged.append(token)
    return merged


def merge_template(
    old_tpl: list[TemplateToken],
    new_tokens: list[str],
    lcs_tokens: list[str],
) -> list[TemplateToken]:
    if not old_tpl:
        return list(new_tokens)

    if not new_tokens:
        return compress_variable_slots(list(old_tpl))

    if not lcs_tokens:
        return [None]

    merged: list[TemplateToken] = []
    old_idx = 0
    new_idx = 0

    for common in lcs_tokens:
        has_gap = False

        while old_idx < len(old_tpl) and old_tpl[old_idx] != common:
            has_gap = True
            old_idx += 1

        while new_idx < len(new_tokens) and new_tokens[new_idx] != common:
            has_gap = True
            new_idx += 1

        if has_gap:
            _append_variable_slot(merged)

        if old_idx < len(old_tpl):
            merged.append(old_tpl[old_idx])
            old_idx += 1

        if new_idx < len(new_tokens):
            new_idx += 1

    if old_idx < len(old_tpl) or new_idx < len(new_tokens):
        _append_variable_slot(merged)

    return compress_variable_slots(merged)


def extract_parameters(
    tokens: list[str], template_tokens: list[TemplateToken]
) -> list[str]:
    if not tokens or not template_tokens:
        return []

    parameters: list[str] = []
    token_idx = 0
    tpl_idx = 0

    while tpl_idx < len(template_tokens):
        template_token = template_tokens[tpl_idx]

        if template_token is not None:
            if token_idx < len(tokens) and tokens[token_idx] == template_token:
                token_idx += 1
            else:
                seek_idx = token_idx
                while seek_idx < len(tokens) and tokens[seek_idx] != template_token:
                    seek_idx += 1
                token_idx = seek_idx + 1 if seek_idx < len(tokens) else len(tokens)

            tpl_idx += 1
            continue

        tpl_idx += 1
        capture_start = token_idx

        if tpl_idx >= len(template_tokens):
            token_idx = len(tokens)
        else:
            next_fixed = template_tokens[tpl_idx]
            while (
                token_idx < len(tokens)
                and next_fixed is not None
                and tokens[token_idx] != next_fixed
            ):
                token_idx += 1

        captured = tokens[capture_start:token_idx]
        parameters.append(" ".join(captured))

    return parameters


def variable_count(template_tokens: list[TemplateToken]) -> int:
    return sum(1 for token in template_tokens if token is None)


def variable_label(
    var_index: int, variable_names: Mapping[int, str] | None = None
) -> str:
    if variable_names is not None:
        name = variable_names.get(var_index)
        if name is not None and name.strip():
            return name.strip()

    return f"var_{var_index}"


def render_template_tokens(
    template_tokens: list[TemplateToken],
    variable_names: Mapping[int, str] | None = None,
) -> list[str]:
    rendered: list[str] = []
    var_index = 0

    for token in template_tokens:
        if token is None:
            rendered.append(f"<VAR:{variable_label(var_index, variable_names)}>")
            var_index += 1
        else:
            rendered.append(token)

    return rendered


def build_named_parameters(
    parameters: list[str],
    variable_names: Mapping[int, str] | None = None,
) -> dict[str, str]:
    return {
        variable_label(var_index, variable_names): value
        for var_index, value in enumerate(parameters)
    }
