from pathlib import Path

import main

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_release_is_v1041():
    assert main.BROWSER_VERSION == "10.5.38"


def test_visual_polish_defaults_use_aurora_preset():
    custom = main._normalized_customization({})
    assert custom["preset"] == "Aurora Glass"
    assert custom["show_version_in_title"] is False
    assert custom["app_bar_height"] >= 38
    assert custom["tab_bar_height"] >= 44
    assert custom["toolbar_height"] >= 62


def test_visual_polish_code_paths_exist():
    for token in (
        '"Aurora": dict(UI_COLOR_DEFAULTS)',
        'text=f"Tekzite',
        'highlightthickness=1, highlightbackground=self.ui["border_soft"]',
        'normal_bg = self.ui["field"] if active else self.ui["chrome"]',
        'self.tab_bar = tk.Frame(self.root, bg=self.ui["chrome"]',
    ):
        assert token in MAIN

