from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NET = (ROOT / "engine" / "net.py").read_text(encoding="utf-8")


def test_dwm_input_offset_is_crop_minus_render_origin():
    start = NET.index("def _dwm_input_offset_for_crop")
    end = NET.index("def _resize_existing_dwm_thumbnail_fast", start)
    helper = NET[start:end]
    assert "dx = float(crop_left) - render_x" in helper
    assert "dy = float(crop_top) - render_y" in helper


def test_full_recrop_refreshes_pointer_alignment_after_final_render_measurement():
    start = NET.index("def _position_native_chromium_overlay")
    end = NET.index("def _wait_for_live_embed_owner", start)
    block = NET[start:end]
    assert "source_render_x, source_render_y = ox_after, oy_after" in block
    assert 'session["dwm_input_crop_origin"] = (0, crop_top)' in block
    assert '_dwm_input_offset_for_crop(' in block
    assert '"crop-minus-render-origin"' in block


def test_fast_resize_preserves_renderer_origin_correction():
    start = NET.index("def _resize_existing_dwm_thumbnail_fast")
    end = NET.index("def request_embedded_chromium_dwm_recrop", start)
    block = NET[start:end]
    assert 'session.get("dwm_source_render_offset_after_expand")' in block
    assert 'session["dwm_input_offset"] = _dwm_input_offset_for_crop' in block
