from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
FEATURES = (ROOT / "browser_features.py").read_text(encoding="utf-8")


def test_settings_uses_short_privacy_and_interface_copy():
    block = MAIN[MAIN.index('def show_preferences'):MAIN.index('def _raise_toplevel_above_dwm')]
    assert "Privacy Lockdown: do not save history or open tabs" in block
    assert "Local suggestions only. Typing stays on this device." in block
    assert "Preview is immediate. Save makes it permanent." in block
    assert "Windows confirmation is required." in block
    assert "Privacy Lockdown: never persist browsing history" not in block


def test_shared_dialog_header_is_not_text_heavy():
    block = MAIN[MAIN.index('def _apply_about_style_to_dialog'):MAIN.index('def _new_animated_toplevel')]
    assert 'text=f"v{BROWSER_VERSION}"' in block
    assert 'Tekzite Browser  •  v' not in block


def test_customization_and_privacy_dialog_intros_are_compact():
    assert "Profile-specific appearance and behavior." in MAIN
    assert "Live privacy status. Destinations are not stored here." in MAIN


def test_network_dialog_removes_large_explanatory_paragraphs():
    assert "Live Tekzite/Chromium sockets." in FEATURES
    assert "Hostnames are exact; request attribution stays in RAM." in FEATURES
    assert "Attribution is RAM-only. Details fetch source on demand; PTR may use DNS." in FEATURES
    assert "Strong opener" not in FEATURES


def test_request_details_keep_privacy_boundary_concise():
    assert "No payloads or full script source are retained. Header names are presence hints only." in FEATURES
    assert "Script source is analyzed on demand and not stored." in FEATURES
