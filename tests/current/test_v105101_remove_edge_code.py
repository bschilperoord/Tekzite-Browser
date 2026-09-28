from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NET = (ROOT / "engine" / "net.py").read_text(encoding="utf-8")
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
FEATURES = (ROOT / "engine" / "features.py").read_text(encoding="utf-8")
BROWSER_FEATURES = (ROOT / "browser_features.py").read_text(encoding="utf-8")
LAUNCHER = (ROOT / "ultraspeed_launcher.py").read_text(encoding="utf-8")


def test_chromium_session_names_have_no_legacy_edge_identity():
    legacy_session = "_ED" + "GE_SESSION"
    legacy_profile = "_persistent_" + "edge_profile_dir"
    for source in (NET, MAIN, FEATURES, BROWSER_FEATURES, LAUNCHER):
        assert legacy_session not in source
        assert legacy_profile not in source


def test_chromium_launch_flags_have_no_edge_only_features():
    edge_first_run = "EdgeFirstRun" + "Experience"
    edge_sidebar = "ms" + "EdgeSidebarV2"
    assert edge_first_run not in NET
    assert edge_sidebar not in NET


def test_chromium_session_names_are_explicit():
    assert "_CHROMIUM_SESSION = None" in NET
    assert "_CHROMIUM_SESSION_LOCK = threading.RLock()" in NET
    assert "def _persistent_chromium_profile_dir" in NET
