from pathlib import Path
import json

import main


ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
FEATURES = (ROOT / "browser_features.py").read_text(encoding="utf-8")
ENGINE = (ROOT / "engine" / "features.py").read_text(encoding="utf-8")
EXTENSION_JS = (ROOT / "chromium_zoom_extension" / "features.js").read_text(encoding="utf-8")
MANIFEST = json.loads((ROOT / "chromium_zoom_extension" / "manifest.json").read_text(encoding="utf-8"))


def test_extension_toolbar_sits_after_downloads():
    assert main.TOOLBAR_ITEM_IDS == (
        "back", "forward", "reload", "home", "address",
        "downloads", "extensions", "menu",
    )
    build = MAIN[MAIN.index("self.downloads_button ="):MAIN.index("self._apply_toolbar_layout()", MAIN.index("self.downloads_button ="))]
    assert build.index("self.downloads_button =") < build.index("self.extensions_toolbar_frame =") < build.index("self.main_menu_button =")
    assert '"extensions": self.extensions_toolbar_frame' in build


def test_existing_extensions_migrate_to_pinned():
    rows = main._normalized_extension_entries([
        {"path": ".", "enabled": True},
    ])
    assert rows
    assert rows[0]["enabled"] is True
    assert rows[0]["pinned"] is True


def test_real_chromium_extension_inventory_bridge_is_used():
    assert "management" in MANIFEST["permissions"]
    assert 'action === "extensionInventory"' in EXTENSION_JS
    assert "chrome.management.getAll()" in EXTENSION_JS
    assert "optionsUrl" in EXTENSION_JS
    assert "def extension_inventory" in ENGINE


def test_toolbar_opens_extension_owned_options_page():
    assert "def _open_actual_extension_settings" in FEATURES
    block = FEATURES[
        FEATURES.index("def _open_actual_extension_settings"):
        FEATURES.index("def _show_extension_toolbar_context_menu")
    ]
    assert "features.extension_inventory()" in block
    assert "optionsUrl" in block
    assert "chrome-extension://" in block
    assert "chrome://extensions/?id=" in block
    assert "self._new_tab(url=target, switch=True, navigate=True)" in block


def test_toolbar_uses_extension_manifest_icon_and_pin_state():
    assert "def _extension_icon_photo" in FEATURES
    assert "ImageTk.PhotoImage" in FEATURES
    assert "def _set_extension_pinned" in FEATURES
    assert "def _refresh_extension_toolbar" in FEATURES
    assert "row.get('pinned', True)" in FEATURES
    assert "Pin / Unpin" in FEATURES
