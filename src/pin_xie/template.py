from __future__ import annotations


WILDCARD = "*"


def _append_wildcard(tokens: list[str]) -> None:
    if not tokens or tokens[-1] != WILDCARD:
        tokens.append(WILDCARD)


def compress_wildcards(tokens: list[str]) -> list[str]:
    merged: list[str] = []
    for token in tokens:
        if token == WILDCARD:
            _append_wildcard(merged)
        else:
            merged.append(token)
    return merged


def merge_template(
    old_tpl: list[str], new_tokens: list[str], lcs_tokens: list[str]
) -> list[str]:
    if not old_tpl:
        return list(new_tokens)

    if not new_tokens:
        return compress_wildcards(list(old_tpl))

    if not lcs_tokens:
        return [WILDCARD]

    merged: list[str] = []
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
            _append_wildcard(merged)

        if old_idx < len(old_tpl):
            merged.append(old_tpl[old_idx])
            old_idx += 1

        if new_idx < len(new_tokens):
            new_idx += 1

    if old_idx < len(old_tpl) or new_idx < len(new_tokens):
        _append_wildcard(merged)

    return compress_wildcards(merged)


def extract_parameters(tokens: list[str], template_tokens: list[str]) -> list[str]:
    if not tokens or not template_tokens:
        return []

    parameters: list[str] = []
    token_idx = 0
    tpl_idx = 0

    while tpl_idx < len(template_tokens):
        template_token = template_tokens[tpl_idx]

        if template_token != WILDCARD:
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
            while token_idx < len(tokens) and tokens[token_idx] != next_fixed:
                token_idx += 1

        captured = tokens[capture_start:token_idx]
        parameters.append(" ".join(captured))

    return parameters
