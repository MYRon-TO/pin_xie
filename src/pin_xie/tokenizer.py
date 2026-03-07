from __future__ import annotations

from collections.abc import Iterable

import jieba
import regex


DEFAULT_DELIMITERS = r"[ =,:()\[\]\t\n\r]+"


class LogTokenizer:
    def __init__(
        self,
        delimiters: str = DEFAULT_DELIMITERS,
        extra_delimiters: Iterable[str] | None = None,
        mask_patterns: Iterable[str] | None = None,
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

        ordered_masks = tuple(mask_patterns) if mask_patterns is not None else ()
        self.mask_patterns = ordered_masks
        self.mask_re = (
            regex.compile("|".join(f"(?:{pattern})" for pattern in ordered_masks))
            if ordered_masks
            else None
        )

        self.use_jieba = use_jieba

    def tokenize(self, log: str) -> list[str]:
        if not log:
            return []

        if self.mask_re is None:
            return self._tokenize_plain_text(log)

        tokens: list[str] = []
        text_pos = 0
        for match in self.mask_re.finditer(log):
            start, end = match.span()
            if text_pos < start:
                tokens.extend(self._tokenize_plain_text(log[text_pos:start]))

            tokens.append(match.group(0))
            text_pos = end

        if text_pos < len(log):
            tokens.extend(self._tokenize_plain_text(log[text_pos:]))

        return [token for token in tokens if token and not token.isspace()]

    def _tokenize_plain_text(self, text: str) -> list[str]:
        if not text:
            return []

        rough_chunks = [chunk for chunk in self.delimiter_re.split(text) if chunk]
        tokens: list[str] = []
        for chunk in rough_chunks:
            tokens.extend(self._segment_chunk(chunk))

        return [token for token in tokens if token and not token.isspace()]

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


def tokenize(log: str, delimiters: str = DEFAULT_DELIMITERS) -> list[str]:
    return LogTokenizer(delimiters=delimiters).tokenize(log)
