from __future__ import annotations

# pyright: reportAny=false, reportMissingTypeStubs=false, reportUnknownArgumentType=false, reportUnknownMemberType=false, reportUnknownVariableType=false
from collections.abc import Iterable
from typing import final

import jieba
import regex

from .models import InputToken, MaskPattern, PlainTokenSource, RegexTokenSource

DEFAULT_DELIMITERS = r"[ =,:()\[\]\t\n\r]+"


@final
class LogTokenizer:
    def __init__(
        self,
        delimiters: str = DEFAULT_DELIMITERS,
        extra_delimiters: Iterable[str] | None = None,
        mask_patterns: Iterable[MaskPattern] | None = None,
        use_jieba: bool = True,
    ) -> None:
        delimiter_patterns = [delimiters]
        if extra_delimiters:
            delimiter_patterns.extend(extra_delimiters)

        self.delimiter_pattern = "|".join(
            f"(?:{pattern})" for pattern in delimiter_patterns
        )
        self.delimiter_re = regex.compile(self.delimiter_pattern)
        self.mixed_chunk_re = regex.compile(
            r"\p{Han}+|[A-Za-z_][A-Za-z0-9_]*|\d+(?:\.\d+)*|[^\s]"
        )
        self.contains_han_re = regex.compile(r"\p{Han}")

        self.mask_patterns = tuple(mask_patterns) if mask_patterns is not None else ()
        user_group_names: set[str] = set()
        for mask in self.mask_patterns:
            user_group_names.update(regex.compile(mask.pattern).groupindex)

        internal_group_names: list[str] = []
        candidate_index = 0
        for _mask in self.mask_patterns:
            while True:
                candidate = f"__pin_xie_mask_{candidate_index}"
                candidate_index += 1
                if candidate not in user_group_names:
                    break
            internal_group_names.append(candidate)
        self._mask_group_names = tuple(internal_group_names)
        self.mask_re = (
            regex.compile(
                "|".join(
                    f"(?P<{group_name}>{mask.pattern})"
                    for group_name, mask in zip(
                        self._mask_group_names, self.mask_patterns, strict=True
                    )
                )
            )
            if self.mask_patterns
            else None
        )
        self.use_jieba = use_jieba

    def tokenize(self, log: str) -> list[InputToken]:
        if not log:
            return []

        if self.mask_re is None:
            return self._tokenize_plain_text(log)

        tokens: list[InputToken] = []
        text_pos = 0
        for match in self.mask_re.finditer(log):
            start, end = match.span()
            if text_pos < start:
                tokens.extend(self._tokenize_plain_text(log[text_pos:start]))

            mask_index = next(
                index
                for index, group_name in enumerate(self._mask_group_names)
                if match.group(group_name) is not None
            )
            tokens.append(
                InputToken(
                    text=match.group(0),
                    source=RegexTokenSource(
                        mask_name=self.mask_patterns[mask_index].name
                    ),
                )
            )
            text_pos = end

        if text_pos < len(log):
            tokens.extend(self._tokenize_plain_text(log[text_pos:]))

        return [token for token in tokens if token.text and not token.text.isspace()]

    def _tokenize_plain_text(self, text: str) -> list[InputToken]:
        if not text:
            return []

        rough_chunks = [chunk for chunk in self.delimiter_re.split(text) if chunk]
        tokens: list[InputToken] = []
        for chunk in rough_chunks:
            tokens.extend(
                InputToken(text=token, source=PlainTokenSource())
                for token in self._segment_chunk(chunk)
            )

        return [token for token in tokens if token.text and not token.text.isspace()]

    def _segment_chunk(self, chunk: str) -> list[str]:
        if chunk.isascii():
            return [chunk]

        segmented: list[str] = []
        for part in self.mixed_chunk_re.findall(chunk):
            if not part or part.isspace():
                continue

            if self.contains_han_re.search(part):
                if self.use_jieba:
                    segmented.extend(
                        token.strip()
                        for token in jieba.cut(part, HMM=True)
                        if token.strip()
                    )
                else:
                    segmented.extend(ch for ch in part if not ch.isspace())
            else:
                segmented.append(part)

        return segmented


def tokenize(log: str, delimiters: str = DEFAULT_DELIMITERS) -> list[InputToken]:
    return LogTokenizer(delimiters=delimiters).tokenize(log)
