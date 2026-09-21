from pathlib import Path

import main

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_release_version():
    assert main.BROWSER_VERSION == "10.5.38"


def test_omnibox_preview_uses_supersampled_canvas():
    block = MAIN[MAIN.index("def _render_address_preview"):MAIN.index("def _activate_address_preview")]
    assert 'oversample = max(2, int(round(max(1.0, scaling))))' in block
    assert 'Image.new("RGB", (w * oversample, h * oversample), fill)' in block
    assert 'point_size * max(1.0, scaling) * oversample' in block


def test_omnibox_preview_downsamples_with_lanczos():
    block = MAIN[MAIN.index("def _render_address_preview"):MAIN.index("def _activate_address_preview")]
    assert 'image = image.resize((w, h), Image.Resampling.LANCZOS)' in block


def test_omnibox_preview_still_uses_real_entry_photo_swap():
    block = MAIN[MAIN.index("def _render_address_preview"):MAIN.index("def _activate_address_preview")]
    assert 'self._address_preview_photo = photo' in block
    assert 'preview.create_image(0, 0, image=photo, anchor="nw")' in block

