import inspect

import main


INSPECT_SOURCE = inspect.getsource(main.BrowserApp.inspect_html)


def test_html_inspector_keeps_live_chromium_dom_path():
    assert "get_embedded_chromium_html" in INSPECT_SOURCE
    assert "self._executor.submit(get_embedded_chromium_html)" in INSPECT_SOURCE


def test_html_inspector_has_structured_editor_header_and_footer():
    assert "</>  HTML Source" in INSPECT_SOURCE
    assert "LIVE DOM" in INSPECT_SOURCE
    assert "RESPONSE SOURCE" in INSPECT_SOURCE
    assert "Read-only" in INSPECT_SOURCE
    assert "lines  •  " in INSPECT_SOURCE
    assert "elements  •  " in INSPECT_SOURCE


def test_html_inspector_has_semantic_syntax_palette():
    for tag in (
        "html_comment",
        "html_doctype",
        "html_bracket",
        "html_tag",
        "html_attr",
        "html_value",
        "html_entity",
        "html_script",
        "html_style",
    ):
        assert tag in INSPECT_SOURCE


def test_html_inspector_search_is_bidirectional_and_counted():
    assert 'toolbar_button("Previous", find_previous)' in INSPECT_SOURCE
    assert 'toolbar_button("Next", find_next)' in INSPECT_SOURCE
    assert 'find_entry.bind("<Shift-Return>", find_previous)' in INSPECT_SOURCE
    assert 'match_var.set(f"{position + 1:,} / {len(matches):,}")' in INSPECT_SOURCE


def test_html_inspector_preserves_native_source_path():
    assert 'self._current_document.get("html") or ""' in INSPECT_SOURCE
    assert "No native HTML source is currently loaded." in INSPECT_SOURCE
