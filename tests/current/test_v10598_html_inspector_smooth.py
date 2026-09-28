import inspect

import main


INSPECT_SOURCE = inspect.getsource(main.BrowserApp.inspect_html)
INIT_SOURCE = inspect.getsource(main.BrowserApp.__init__)
CLOSE_SOURCE = inspect.getsource(main.BrowserApp.on_close)


def test_html_inspector_never_inserts_entire_dom_in_one_tk_call():
    assert "source_insert_chunk_chars = 8192" in INSPECT_SOURCE
    assert 'text.insert("end", html[offset:end])' in INSPECT_SOURCE
    assert 'text.insert("1.0", html)' not in INSPECT_SOURCE
    assert "source_insert_frame_ms = 1" in INSPECT_SOURCE


def test_html_inspector_tk_tag_work_has_strict_time_budget():
    assert "ui_slice_budget_ms = 3.0" in INSPECT_SOURCE
    assert "time.perf_counter() + (ui_slice_budget_ms / 1000.0)" in INSPECT_SOURCE
    assert "highlight_batch_size = 64" in INSPECT_SOURCE
    assert "search_tag_batch_size = 48" in INSPECT_SOURCE


def test_html_inspector_search_scans_off_tk_thread():
    assert "def build_search_plan" in INSPECT_SOURCE
    assert "self._html_inspector_executor.submit(" in INSPECT_SOURCE
    assert "build_search_plan, source_state" in INSPECT_SOURCE
    assert 'match_var.set("Searching…")' in INSPECT_SOURCE


def test_html_inspector_worker_is_serialized_and_cooperatively_yields():
    assert "max_workers=1" in INIT_SOURCE
    assert 'thread_name_prefix="tekzite-html-inspector"' in INIT_SOURCE
    assert "time.sleep(0)" in INSPECT_SOURCE
    assert "_html_inspector_executor.shutdown" in CLOSE_SOURCE


def test_html_inspector_background_coloring_yields_to_user_interaction():
    assert "interaction_state" in INSPECT_SOURCE
    assert "inspector_interaction_active()" in INSPECT_SOURCE
    assert 'text.bind(sequence, note_inspector_interaction, add="+")' in INSPECT_SOURCE
    assert 'widget.bind("<B1-Motion>", note_inspector_interaction, add="+")' in INSPECT_SOURCE
