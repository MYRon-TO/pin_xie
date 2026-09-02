# pyright: standard
from pin_xie.cluster import LCSObject
from pin_xie.lcs import lcs
from pin_xie.models import (
    InputToken,
    LiteralTemplateToken,
    PlainTokenSource,
    RegexTokenSource,
    VariableTemplateToken,
)
from pin_xie.similarity import jaccard_filter
from pin_xie.trie import PrefixTree

PLAIN = PlainTokenSource()
REGEX = RegexTokenSource(mask_name="number")


def input_token(text: str, *, regex: bool = False) -> InputToken:
    return InputToken(text=text, source=REGEX if regex else PLAIN)


def literal(text: str, *, regex: bool = False) -> LiteralTemplateToken:
    source = REGEX if regex else PLAIN
    return LiteralTemplateToken(text=text, sources=(source,))


def variable(name: str, *, regex: bool = False) -> VariableTemplateToken:
    source = REGEX if regex else PLAIN
    return VariableTemplateToken(var_name=name, sources=(source,))


def test_lcs_uses_literal_text_only_and_preserves_template_tie_break() -> None:
    template = [literal("A", regex=True), variable("ignored"), literal("B")]
    tokens = [input_token("B", regex=True), input_token("A")]

    assert lcs(template, tokens) == (1, ["A"])
    assert lcs(
        [literal("A"), variable("another_name", regex=True), literal("B", regex=True)],
        [input_token("B"), input_token("A", regex=True)],
    ) == (1, ["A"])


def test_lcs_variable_token_never_matches_input_text() -> None:
    assert lcs([variable("value")], [input_token("value")]) == (0, [])


def test_jaccard_filter_ignores_input_source() -> None:
    cluster = LCSObject(1, [literal("A"), literal("B", regex=True)])

    assert jaccard_filter(
        [input_token("A"), input_token("B", regex=True)], [cluster]
    ) == [cluster]
    assert jaccard_filter(
        [input_token("A", regex=True), input_token("B")], [cluster]
    ) == [cluster]


def test_jaccard_filter_repeated_tokens_still_raise_threshold() -> None:
    cluster = LCSObject(1, [literal("A"), literal("B")])

    assert (
        jaccard_filter(
            [input_token("A"), input_token("A"), input_token("B"), input_token("B")],
            [cluster],
        )
        == []
    )


def test_trie_ignores_sources_and_variable_names() -> None:
    cluster = LCSObject(1, [literal("A", regex=True), variable("first"), literal("B")])
    trie = PrefixTree()
    trie.insert(cluster)

    assert (
        trie.match(
            [
                input_token("A"),
                input_token("value", regex=True),
                input_token("B", regex=True),
            ],
            {1: cluster},
        )
        == 1
    )

    renamed = LCSObject(1, [literal("A"), variable("second", regex=True), literal("B")])
    trie.build([renamed])
    assert (
        trie.match(
            [input_token("A", regex=True), input_token("value"), input_token("B")],
            {1: renamed},
        )
        == 1
    )


def test_trie_candidate_tie_still_prefers_shorter_template() -> None:
    longer = LCSObject(1, [literal("A"), variable("value"), literal("B")])
    shorter = LCSObject(2, [literal("A", regex=True), literal("B")])
    trie = PrefixTree()
    trie.build([longer, shorter])

    assert (
        trie.match(
            [input_token("A", regex=True), input_token("B")],
            {1: longer, 2: shorter},
        )
        == 2
    )
