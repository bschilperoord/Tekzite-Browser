from pathlib import Path
from unittest.mock import patch

import engine.net as net
import main


ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
NET = (ROOT / "engine" / "net.py").read_text(encoding="utf-8")


def test_website_color_scheme_preference_defaults_and_normalizes():
    assert main.DEFAULT_PREFERENCES["website_color_scheme"] == "system"
    assert main._normalized_website_color_scheme("DARK") == "dark"
    assert main._normalized_website_color_scheme("light") == "light"
    assert main._normalized_website_color_scheme("nonsense") == "system"


def test_color_scheme_uses_prefers_color_scheme_cdp_feature():
    session = {"port": 9222, "target_id": "page-1", "page_cdp_channels": {}}
    with patch.object(net, "_EDGE_SESSION", session), \
         patch.object(net, "_persistent_page_cdp_call", return_value={}) as call:
        assert net.set_embedded_chromium_color_scheme("dark", "page-1")
    call.assert_called_once()
    assert call.call_args.args[1] == "Emulation.setEmulatedMedia"
    assert call.call_args.args[2] == {
        "media": "",
        "features": [{"name": "prefers-color-scheme", "value": "dark"}],
    }


def test_system_color_scheme_clears_override():
    session = {"port": 9222, "target_id": "page-1", "page_cdp_channels": {}}
    with patch.object(net, "_EDGE_SESSION", session), \
         patch.object(net, "_persistent_page_cdp_call", return_value={}) as call:
        assert net.set_embedded_chromium_color_scheme("system", "page-1")
    assert call.call_args.args[2] == {"media": "", "features": []}


def test_settings_exposes_website_color_scheme():
    block = MAIN[MAIN.index("def show_preferences"):MAIN.index("def _raise_toplevel_above_dwm")]
    assert 'text="Website color scheme"' in block
    assert 'combo(website_color_scheme, ["system", "dark", "light"])' in block
    assert '"website_color_scheme": _normalized_website_color_scheme(website_color_scheme.get())' in block


def test_open_chromium_seeds_color_scheme_before_target_creation():
    start = NET.index("def open_embedded_chromium")
    end = NET.index("\ndef ", start + 10)
    block = NET[start:end]
    seed = block.index('session["website_color_scheme"] = preferred_color_scheme')
    claim = block.index("if attach_native and not target_id and not create_new_target:")
    assert seed < claim
    assert "website_color_scheme_pre_navigation_applied" in block
