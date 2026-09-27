import inspect

import main


INSPECT_SOURCE = inspect.getsource(main.BrowserApp.inspect_html)


def test_html_inspector_defers_syntax_work_past_open_animation():
    assert "highlight_start_delay_ms = 210" in INSPECT_SOURCE
    assert "after_idle(" not in INSPECT_SOURCE


def test_html_inspector_parses_syntax_off_tk_thread():
    assert "build_highlight_plan" in INSPECT_SOURCE
    assert "self._executor.submit(" in INSPECT_SOURCE
    assert "build_highlight_plan, html, generation" in INSPECT_SOURCE


def test_html_inspector_applies_color_tags_in_small_batches():
    assert "highlight_batch_size = 240" in INSPECT_SOURCE
    assert "apply_highlight_plan(plan, stop)" in INSPECT_SOURCE
    assert "window.after(" in INSPECT_SOURCE


def test_html_inspector_preserves_existing_source_and_search_paths():
    assert "get_embedded_chromium_html" in INSPECT_SOURCE
    assert 'self._current_document.get("html") or ""' in INSPECT_SOURCE
    assert "find_previous" in INSPECT_SOURCE
    assert "find_next" in INSPECT_SOURCE
