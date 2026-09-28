import inspect

import main


INSPECT_SOURCE = inspect.getsource(main.BrowserApp.inspect_html)


def test_html_inspector_has_rich_css_semantic_palette():
    for tag in (
        "css_selector",
        "css_at_rule",
        "css_property",
        "css_value",
        "css_string",
        "css_number",
        "css_color",
        "css_function",
        "css_variable",
        "css_important",
        "css_punctuation",
        "css_comment",
    ):
        assert tag in INSPECT_SOURCE


def test_html_inspector_parses_only_real_css_regions():
    assert "css_regions = []" in INSPECT_SOURCE
    assert 'attr_name.lower() == "style"' in INSPECT_SOURCE
    assert 'r"<(script|style)\\b[^>]*>(.*?)</\\1\\s*>"' in INSPECT_SOURCE
    assert "tokenize_css_region(" in INSPECT_SOURCE
    assert "declarations_only=declarations_only" in INSPECT_SOURCE


def test_html_inspector_markup_tokens_are_more_semantic():
    assert '"html_equals"' in INSPECT_SOURCE
    assert '"html_quote"' in INSPECT_SOURCE
    assert "html_token_pattern = re.compile(" in INSPECT_SOURCE
    assert "embedded_regions" in INSPECT_SOURCE


def test_html_inspector_groups_equal_color_ranges_for_tk_speed():
    assert '"groups": groups' in INSPECT_SOURCE
    assert '"tag_order": tag_order' in INSPECT_SOURCE
    assert "highlight_calls_per_slice = 3" in INSPECT_SOURCE
    assert "text.tag_add(tag_name, *args)" in INSPECT_SOURCE
    assert "range_index + highlight_batch_size" in INSPECT_SOURCE


def test_css_parser_is_linear_and_cooperatively_yields():
    assert "def tokenize_css_region" in INSPECT_SOURCE
    assert "while i < n and span_count < highlight_span_limit" in INSPECT_SOURCE
    assert "worker_yield()" in INSPECT_SOURCE
    assert "time.sleep(0)" in INSPECT_SOURCE
