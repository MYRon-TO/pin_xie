# pyright: standard
import pytest
from pin_xie.cluster import LCSObject, create_cluster
from pin_xie.models import (
    InputToken,
    LiteralTemplateToken,
    PlainTokenSource,
    RegexTokenSource,
    TokenSource,
    VariableTemplateToken,
)
from pin_xie.template import extract_parameters, merge_template, render_template_tokens

PLAIN = PlainTokenSource()
IP = RegexTokenSource("ipv4")
PORT = RegexTokenSource("port")


def inp(text: str, source: TokenSource = PLAIN) -> InputToken:
    return InputToken(text, source)


def literal(text: str, *sources: TokenSource) -> LiteralTemplateToken:
    return LiteralTemplateToken(text, sources or (PLAIN,))


def variable(name: str, *sources: TokenSource) -> VariableTemplateToken:
    return VariableTemplateToken(name, sources or (PLAIN,))


def test_create_cluster_uses_literal_objects_and_distinct_literal_count() -> None:
    cluster = create_cluster(1, [inp("a"), inp("a", IP)], 7)
    assert [token.kind for token in cluster.template_tokens] == ["literal", "literal"]
    assert cluster.template_tokens[1].sources == (IP,)
    assert cluster.token_set == {"a"}
    assert cluster.constant_token_count == 1


def test_matching_literal_accumulates_sources() -> None:
    merged = merge_template([literal("host")], [inp("host", IP)], ["host"])
    assert merged == [literal("host", PLAIN, IP)]


def test_difference_generalizes_with_mixed_and_multiple_sources() -> None:
    merged = merge_template([literal("x", PLAIN, IP)], [inp("y", PORT)], [])
    assert merged == [variable("var_0", PLAIN, IP, PORT)]


def test_existing_variable_identity_survives_inserted_variable_before_it() -> None:
    old = [literal("a"), variable("client"), literal("b")]
    merged = merge_template(
        old, [inp("new"), inp("a"), inp("value"), inp("b")], ["a", "b"]
    )
    assert [token.var_name for token in merged if token.kind == "variable"] == [
        "var_0",
        "client",
    ]


def test_adjacent_different_variables_get_new_name_and_union_sources() -> None:
    merged = merge_template(
        [variable("left", IP), variable("right", PORT)], [inp("x")], []
    )
    assert merged == [variable("var_0", PLAIN, IP, PORT)]


def test_no_lcs_single_variable_preserves_identity() -> None:
    assert merge_template([variable("custom", IP)], [inp("x")], []) == [
        variable("custom", PLAIN, IP)
    ]


def test_variable_rename_is_atomic_supports_swap_and_reset() -> None:
    cluster = LCSObject(1, [variable("first"), literal("x"), variable("second")])
    cluster.replace_variable_names({0: " second ", 1: "first"})
    assert cluster.get_variable_names() == {0: "second", 1: "first"}

    before = list(cluster.template_tokens)
    with pytest.raises(ValueError):
        cluster.replace_variable_names({0: "same", 1: "same"})
    assert cluster.template_tokens == before

    cluster.set_variable_name(0, None)
    assert cluster.get_variable_names() == {0: "var_0", 1: "first"}
    cluster.set_variable_name(1, "  ")
    assert cluster.get_variable_names() == {0: "var_0", 1: "var_1"}


def test_parameter_capture_uses_input_sources_and_full_template_index() -> None:
    template = [literal("a"), variable("client", PLAIN, PORT), literal("z")]
    captures = extract_parameters([inp("a"), inp("10", IP), inp("z")], template)
    assert len(captures) == 1
    capture = captures[0]
    assert (capture.template_token_index, capture.var_name, capture.value) == (
        1,
        "client",
        "10",
    )
    assert capture.sources == (IP,)


def test_parameter_multi_token_and_repeated_fixed_boundary() -> None:
    template = [literal("a"), variable("value"), literal("x")]
    capture = extract_parameters(
        [inp("a"), inp("one", IP), inp("two", PORT), inp("x"), inp("x")],
        template,
    )[0]
    assert capture.value == "one two"
    assert capture.sources == (IP, PORT)


def test_render_reads_object_variable_name() -> None:
    assert render_template_tokens([literal("a"), variable("client")]) == [
        "a",
        "<VAR:client>",
    ]
