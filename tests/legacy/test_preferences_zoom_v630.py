from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
NET = (ROOT / "engine" / "net.py").read_text(encoding="utf-8")


def test_version_v630():
    assert 'BROWSER_VERSION = "6.3"' in MAIN


def test_preferences_zoom_is_passed_into_open_chromium():
    assert "self._page_zoom_percent()," in MAIN
    assert "preferred_zoom_percent: int = 100" in NET


def test_session_zoom_is_seeded_before_target_claim_or_creation():
    seed = NET.index('session["default_page_zoom_percent"] = preferred_zoom_percent')
    claim = NET.index('if attach_native and not target_id and not create_new_target:', seed)
    assert seed < claim
    assert 'session["preferences_zoom_seeded_before_target"] = True' in NET


def test_existing_target_gets_zoom_before_navigation_and_after():
    pre = NET.index('session["preferences_zoom_pre_navigation_applied"] = True')
    nav = NET.index('session = navigate_embedded_chromium(', pre)
    post = NET.index('session["preferences_zoom_post_navigation_applied"] = True', nav)
    assert pre < nav < post


def test_new_targets_inherit_browser_wide_zoom_bootstrap():
    assert 'inherited_zoom = int(session.get("default_page_zoom_percent", 100))' in NET
    assert 'set_embedded_chromium_zoom(inherited_zoom, target_id=target_id, timeout=3)' in NET
    assert 'Page.addScriptToEvaluateOnNewDocument' in NET


def test_dwm_stays_presentation_only_for_zoom():
    assert 'session["dwm_thumbnail_scale_x"] = 1.0' in NET
    assert 'session["dwm_thumbnail_scale_y"] = 1.0' in NET


def test_full_debug_exposes_preference_zoom_application():
    for field in (
        "preferences_zoom_percent",
        "preferences_zoom_seeded_before_target",
        "preferences_zoom_pre_navigation_applied",
        "preferences_zoom_post_navigation_applied",
    ):
        assert f"{field}:" in NET
