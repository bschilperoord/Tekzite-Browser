from pathlib import Path

import main
from browser_features import most_visited_sites, record_visit


ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def _method_block(name):
    start = MAIN.index(f"def {name}")
    end = MAIN.find("\n    def ", start + 1)
    return MAIN[start:] if end < 0 else MAIN[start:end]


def test_record_visit_tracks_frequency_compatibly():
    rows = [{"url": "https://example.test/a", "title": "Old", "visited": 1.0}]
    rows = record_visit(rows, "https://example.test/a", "New", now=2.0)
    assert rows[0]["visit_count"] == 2
    assert rows[0]["title"] == "New"
    assert rows[0]["visited"] == 2.0

    rows = record_visit(rows, "https://example.test/a", "Again", now=3.0)
    assert rows[0]["visit_count"] == 3


def test_most_visited_sites_aggregates_by_hostname():
    rows = [
        {"url": "https://example.test/a", "title": "A", "visited": 10, "visit_count": 4},
        {"url": "https://example.test/b", "title": "B", "visited": 20, "visit_count": 3},
        {"url": "https://other.test/", "title": "Other", "visited": 30, "visit_count": 5},
    ]
    result = most_visited_sites(rows, limit=8)
    assert [item["host"] for item in result] == ["example.test", "other.test"]
    assert result[0]["visit_count"] == 7
    assert result[0]["url"] == "https://example.test/a"


def test_most_visited_sites_uses_recency_as_tie_breaker():
    rows = [
        {"url": "https://older.test/", "title": "Older", "visited": 10, "visit_count": 2},
        {"url": "https://newer.test/", "title": "Newer", "visited": 20, "visit_count": 2},
    ]
    result = most_visited_sites(rows, limit=8)
    assert [item["host"] for item in result] == ["newer.test", "older.test"]


def test_empty_tab_panel_is_local_and_bound_to_blank_paths():
    assert "def _render_empty_tab_panel(self):" in MAIN
    block = MAIN[MAIN.index("def _render_empty_tab_panel(self):"):MAIN.index("def _show_native_canvas", MAIN.index("def _render_empty_tab_panel(self):"))]
    assert "most_visited_sites(getattr(self, \"visits\", []), limit=8)" in block
    assert "no network request is made to build this panel" in block
    assert "self.navigate_to(target, reuse_existing=False)" in block
    assert 'self._new_tab(url=target, switch=True, navigate=True)' in block
    assert "def release_blank_tab_omnibox():" in block
    assert "self._release_address_focus_for_navigation()" in block
    assert "self.canvas.focus_set()" in block
    assert block.index("release_blank_tab_omnibox()") < block.index(
        "self.navigate_to(target, reuse_existing=False)"
    )

    new_tab = MAIN[MAIN.index("def _new_tab(self"):MAIN.index("def _capture_active_tab_state")]
    assert "self._render_empty_tab_panel()" in new_tab

    switch = _method_block("_switch_tab(self,")
    assert "self._render_empty_tab_panel()" in switch

    close = _method_block("_close_tab(self")
    assert "self._render_empty_tab_panel()" in close


def test_empty_tab_redraws_on_resize_without_starting_chromium():
    block = _method_block("_on_canvas_configure")
    assert "self._empty_tab_is_active()" in block
    assert "self._render_empty_tab_panel" in block
