from __future__ import annotations

from collections.abc import Iterable

from .models import (
    InputToken,
    LiteralTemplateToken,
    ParameterCapture,
    TemplateToken,
    TokenSource,
    VariableTemplateToken,
    normalize_sources,
)


def is_variable_token(token: TemplateToken) -> bool:
    return token.kind == "variable"


def _next_variable_name(used_names: set[str]) -> str:
    index = 0
    while f"var_{index}" in used_names:
        index += 1
    name = f"var_{index}"
    used_names.add(name)
    return name


def _merged_variable(
    tokens: Iterable[TemplateToken],
    new_tokens: Iterable[InputToken],
    used_names: set[str],
) -> VariableTemplateToken:
    old_tokens = list(tokens)
    incoming = list(new_tokens)
    names = {token.var_name for token in old_tokens if token.kind == "variable"}
    name = names.pop() if len(names) == 1 else _next_variable_name(used_names)
    sources: list[TokenSource] = [
        source for token in old_tokens for source in token.sources
    ]
    sources.extend(token.source for token in incoming)
    return VariableTemplateToken(var_name=name, sources=normalize_sources(sources))


def compress_variable_slots(tokens: list[TemplateToken]) -> list[TemplateToken]:
    used_names = {token.var_name for token in tokens if token.kind == "variable"}
    merged: list[TemplateToken] = []
    for token in tokens:
        if token.kind != "variable" or not merged or merged[-1].kind != "variable":
            merged.append(token)
            continue
        previous = merged.pop()
        merged.append(_merged_variable([previous, token], [], used_names))
    return merged


def merge_template(
    old_tpl: list[TemplateToken],
    new_tokens: list[InputToken],
    lcs_tokens: list[str],
) -> list[TemplateToken]:
    if not old_tpl:
        return [
            LiteralTemplateToken(text=token.text, sources=(token.source,))
            for token in new_tokens
        ]

    used_names = {token.var_name for token in old_tpl if token.kind == "variable"}
    if not lcs_tokens:
        return [_merged_variable(old_tpl, new_tokens, used_names)]

    merged: list[TemplateToken] = []
    old_idx = 0
    new_idx = 0

    for common in lcs_tokens:
        old_end = old_idx
        while old_end < len(old_tpl):
            token = old_tpl[old_end]
            if token.kind == "literal" and token.text == common:
                break
            old_end += 1

        new_end = new_idx
        while new_end < len(new_tokens) and new_tokens[new_end].text != common:
            new_end += 1

        if old_end > old_idx or new_end > new_idx:
            merged.append(
                _merged_variable(
                    old_tpl[old_idx:old_end], new_tokens[new_idx:new_end], used_names
                )
            )

        if old_end < len(old_tpl) and new_end < len(new_tokens):
            old_literal = old_tpl[old_end]
            assert old_literal.kind == "literal"
            merged.append(
                LiteralTemplateToken(
                    text=old_literal.text,
                    sources=(*old_literal.sources, new_tokens[new_end].source),
                )
            )
            old_idx = old_end + 1
            new_idx = new_end + 1

    if old_idx < len(old_tpl) or new_idx < len(new_tokens):
        merged.append(
            _merged_variable(old_tpl[old_idx:], new_tokens[new_idx:], used_names)
        )

    return compress_variable_slots(merged)


def extract_parameters(
    tokens: list[InputToken], template_tokens: list[TemplateToken]
) -> list[ParameterCapture]:
    if not tokens or not template_tokens:
        return []

    parameters: list[ParameterCapture] = []
    token_idx = 0
    tpl_idx = 0

    while tpl_idx < len(template_tokens):
        template_token = template_tokens[tpl_idx]
        if template_token.kind == "literal":
            if (
                token_idx < len(tokens)
                and tokens[token_idx].text == template_token.text
            ):
                token_idx += 1
            else:
                while (
                    token_idx < len(tokens)
                    and tokens[token_idx].text != template_token.text
                ):
                    token_idx += 1
                if token_idx < len(tokens):
                    token_idx += 1
            tpl_idx += 1
            continue

        variable_tpl_index = tpl_idx
        tpl_idx += 1
        capture_start = token_idx
        if tpl_idx >= len(template_tokens):
            token_idx = len(tokens)
        else:
            next_fixed = template_tokens[tpl_idx]
            while (
                token_idx < len(tokens)
                and next_fixed.kind == "literal"
                and tokens[token_idx].text != next_fixed.text
            ):
                token_idx += 1

        captured = tokens[capture_start:token_idx]
        if not captured:
            continue
        parameters.append(
            ParameterCapture(
                template_token_index=variable_tpl_index,
                var_name=template_token.var_name,
                value=" ".join(token.text for token in captured),
                sources=normalize_sources(token.source for token in captured),
            )
        )

    return parameters


def variable_count(template_tokens: list[TemplateToken]) -> int:
    return sum(token.kind == "variable" for token in template_tokens)


def render_template_tokens(template_tokens: list[TemplateToken]) -> list[str]:
    return [
        token.text if token.kind == "literal" else f"<VAR:{token.var_name}>"
        for token in template_tokens
    ]
